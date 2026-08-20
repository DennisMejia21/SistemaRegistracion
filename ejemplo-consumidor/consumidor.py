"""Ejemplo de proyecto que usa el padron para que entre su gente.

Es lo minimo que tiene que hacer un proyecto de la materia: mandar a la persona
al login central y despues canjear el codigo con el que vuelve. Son dos pedidos
HTTP; el resto de este archivo es un servidor de juguete para poder verlo andar.

    Carpooling                 Login central                Padron
        |                            |                         |
        |-- /entrar?proyecto_id=1 -->|                         |
        |                            |-- POST /codigos ------->|
        |<-- /sesion?codigo=... -----|                         |
        |-- POST /codigos/canjear ------------------------------>|
        |<-- {"usuario": {...}} --------------------------------|

Este proyecto NUNCA ve una contraseña. Ni la pide, ni la guarda, ni la recibe.

No usa ninguna libreria: solo la biblioteca estandar de Python, para que se lea
como lo que es (dos pedidos HTTP) y se pueda traducir a cualquier lenguaje.
"""
import html
import json
import os
import secrets
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs, urlencode


# Donde vive el padron, para los pedidos servidor-a-servidor.
PADRON_URL = os.getenv("PADRON_URL", "http://localhost:8000").rstrip("/")

# El token de ESTE proyecto, el que dio de alta la catedra con
# POST /aplicaciones. No es el del login central y no se comparte con nadie.
PADRON_TOKEN = os.getenv("PADRON_TOKEN", "")

# Donde vive el login central. Esta URL la abre el NAVEGADOR de la persona, asi
# que tiene que ser alcanzable desde su maquina (no el nombre de un contenedor).
LOGIN_URL = os.getenv("LOGIN_URL", "http://localhost:3001").rstrip("/")

# Que proyecto es este, segun la tabla `proyectos` del padron.
PROYECTO_ID = int(os.getenv("PROYECTO_ID", "1"))

PUERTO = int(os.getenv("PUERTO", "9000"))


def canjear(codigo):
    """El unico pedido que importa: codigo -> quien es la persona.

    Esto es lo que hay que copiar. El token va en Authorization: Bearer, el
    codigo en el cuerpo, y lo que vuelve es el usuario del padron.
    """
    pedido = urllib.request.Request(
        f"{PADRON_URL}/codigos/canjear",
        data=json.dumps({"codigo": codigo}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {PADRON_TOKEN}",
        },
        method="POST",
    )

    with urllib.request.urlopen(pedido) as respuesta:
        return json.load(respuesta)


def pagina(titulo, cuerpo):
    return f"<!doctype html><meta charset=utf-8><title>{titulo}</title>{cuerpo}"


class Manejador(BaseHTTPRequestHandler):

    def do_GET(self):
        partes = urlparse(self.path)
        consulta = parse_qs(partes.query)

        if partes.path == "/":
            self.mostrar_inicio()

        elif partes.path == "/sesion":
            self.recibir_vuelta(consulta)

        else:
            self.responder(404, pagina("No existe", "<p>No existe.</p>"))

    def mostrar_inicio(self):
        """La pantalla con el boton Ingresar.

        El `state` es un valor al azar que se guarda de este lado y viaja hasta
        el login y de vuelta. Sirve para reconocer la propia ida: si vuelve una
        respuesta con otro state, o sin state, es una vuelta que este proyecto
        nunca empezo, y no se acepta.
        """
        state = secrets.token_urlsafe(16)

        destino = f"{LOGIN_URL}/entrar?" + urlencode({
            "proyecto_id": PROYECTO_ID,
            "state": state,
        })

        cuerpo = (
            "<h1>Carpooling</h1>"
            "<p>Este es el front de un proyecto de la materia.</p>"
            f'<p><a href="{html.escape(destino)}">Ingresar con mi cuenta de PP2</a></p>'
        )

        self.responder(200, pagina("Carpooling", cuerpo), state=state)

    def recibir_vuelta(self, consulta):
        """La vuelta del login: ?codigo=...&state=..."""
        codigo = consulta.get("codigo", [""])[0]
        state = consulta.get("state", [""])[0]
        state_guardado = self.leer_cookie("state")

        if not state_guardado or state != state_guardado:
            self.responder(400, pagina(
                "Carpooling",
                "<h1>Carpooling</h1><p>Esta vuelta no corresponde a un ingreso "
                "que haya empezado acá.</p>",
            ))
            return

        try:
            datos = canjear(codigo)

        except urllib.error.HTTPError as error:
            # 400: el codigo no sirve, vencio, ya se uso o es de otro proyecto.
            # 401: el token de este proyecto no es, o esta revocado.
            self.responder(error.code, pagina(
                "Carpooling",
                f"<h1>Carpooling</h1><p>No se pudo validar el ingreso "
                f"(HTTP {error.code}).</p>",
            ))
            return

        usuario = datos["usuario"]

        # Y acá cada proyecto emite SU sesión, como la tenga hecha. De este
        # punto en adelante ya no hay nada del padrón: es tu aplicación.
        cuerpo = (
            "<h1>Carpooling</h1>"
            f"<p>Entraste como <b>{html.escape(usuario['nombre'])} "
            f"{html.escape(usuario['apellido'])}</b> "
            f"({html.escape(usuario['email'])}).</p>"
            f"<p>Tu id en el padrón es {usuario['id']}. "
            f"Proyecto: {html.escape(datos['proyecto']['nombre'])}.</p>"
            '<p><a href="/">Volver al inicio</a></p>'
        )

        self.responder(200, cuerpo=pagina("Carpooling", cuerpo), borrar_state=True)

    def leer_cookie(self, nombre):
        crudo = self.headers.get("Cookie")
        if not crudo:
            return None

        galletas = SimpleCookie()
        galletas.load(crudo)
        return galletas[nombre].value if nombre in galletas else None

    def responder(self, estado, cuerpo, state=None, borrar_state=False):
        self.send_response(estado)
        self.send_header("Content-Type", "text/html; charset=utf-8")

        if state:
            self.send_header("Set-Cookie", f"state={state}; Path=/; HttpOnly; SameSite=Lax")

        if borrar_state:
            self.send_header("Set-Cookie", "state=; Path=/; Max-Age=0")

        self.end_headers()
        self.wfile.write(cuerpo.encode())

    def log_message(self, formato, *args):
        print(f"[consumidor] {formato % args}")


if __name__ == "__main__":
    if not PADRON_TOKEN:
        raise SystemExit("Falta PADRON_TOKEN: es el token de este proyecto en el padron.")

    print(f"[consumidor] proyecto {PROYECTO_ID} escuchando en el {PUERTO}")
    HTTPServer(("0.0.0.0", PUERTO), Manejador).serve_forever()
