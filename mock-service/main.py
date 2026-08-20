import os
import secrets
from contextlib import contextmanager

import bcrypt
import mysql.connector

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


app = FastAPI(title="Servicio de Registración")


# Token de las aplicaciones que leen el padrón (por ahora, el front de login).
# Va en `Authorization: Bearer`. Sin esto, GET /usuarios queda abierto y
# cualquiera que llegue al puerto se lleva todos los emails.
API_TOKEN = os.getenv("API_TOKEN", "")

# bcrypt no mira mas alla de los 72 bytes de la contraseña. Es un limite del
# algoritmo, no de la columna: `password` es VARCHAR(255) porque ahi entra el
# hash (60 caracteres), no porque la contraseña pueda ser tan larga.
PASSWORD_MAX_BYTES = 72


class Registro(BaseModel):
    nombre: str
    apellido: str
    email: str
    password: str
    proyecto_id: int


class Credenciales(BaseModel):
    email: str
    password: str


@contextmanager
def base_de_datos():
    """Abre conexion y cursor, commitea si sale bien y rollbackea si no.

    Antes cada endpoint abria la conexion a mano y la cerraba solo en el camino
    feliz: si una query fallaba a mitad, la conexion quedaba abierta y la
    transaccion a medias.
    """
    conexion = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "registracion"),
        user=os.getenv("DB_USER", "registracion_user"),
        password=os.getenv("DB_PASSWORD", "registracion_pass")
    )

    cursor = conexion.cursor(dictionary=True)

    try:
        yield cursor
        conexion.commit()

    except Exception:
        conexion.rollback()
        raise

    finally:
        cursor.close()
        conexion.close()


def normalizar_email(email: str) -> str:
    """En la base hay filas cargadas como `Carnero@gmail.com`. Se guarda y se
    busca siempre en minusculas para que el login no dependa de como lo escriban."""
    return email.strip().lower()


def hashear(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verificar(password: str, guardado: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), guardado.encode())

    except ValueError:
        # La fila todavia tiene la contraseña en texto plano (no paso por la
        # migracion): no es un hash valido, asi que no valida.
        return False


def exigir_password_valida(password: str) -> None:
    if len(password.encode()) > PASSWORD_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"La contraseña no puede pasar de {PASSWORD_MAX_BYTES} bytes"
        )


def exigir_token(authorization: str | None) -> None:
    if not API_TOKEN:
        # Error de configuracion del servicio, no del que pide.
        raise HTTPException(status_code=500, detail="API_TOKEN no esta configurado")

    if not authorization or not secrets.compare_digest(authorization, f"Bearer {API_TOKEN}"):
        raise HTTPException(status_code=401, detail="Token invalido")


def proyectos_de(cursor, usuario_id: int) -> list[dict]:
    cursor.execute(
        """
        SELECT p.id, p.nombre
        FROM usuario_proyecto up
        JOIN proyectos p ON p.id = up.proyecto_id
        WHERE up.usuario_id = %s
        ORDER BY p.id
        """,
        (usuario_id,)
    )

    return cursor.fetchall()


def buscar_por_email(cursor, email: str) -> dict | None:
    cursor.execute(
        "SELECT id, nombre, apellido, email, password FROM usuarios WHERE email = %s",
        (email,)
    )

    return cursor.fetchone()


@app.get("/")
def inicio():
    return {
        "mensaje": "Servicio de registración funcionando"
    }


@app.post("/login")
def login(datos: Credenciales):
    """Valida credenciales y devuelve la persona con TODOS sus proyectos.

    Los proyectos van en esta misma respuesta a proposito: el front decide con
    eso si no la deja entrar (cero proyectos), si entra derecho (uno) o si le
    muestra un selector (varios). Mandarlos aca evita un segundo pedido.

    La contraseña no sale nunca de este servicio: se compara aca y se responde
    si es correcta o no.
    """
    email = normalizar_email(datos.email)

    with base_de_datos() as cursor:
        usuario = buscar_por_email(cursor, email)

        # Mismo error para email inexistente y contraseña equivocada: si
        # fueran distintos, se podria averiguar quien tiene cuenta y quien no.
        if usuario is None or not verificar(datos.password, usuario["password"]):
            raise HTTPException(status_code=401, detail="Credenciales invalidas")

        return {
            "id": usuario["id"],
            "nombre": usuario["nombre"],
            "apellido": usuario["apellido"],
            "email": usuario["email"],
            "proyectos": proyectos_de(cursor, usuario["id"])
        }


@app.post("/registrar")
def registrar(datos: Registro):
    """Alta en el padron, ya vinculada a un proyecto.

    Si el email ya existe se reusa esa persona y solo se agrega el vinculo con
    el proyecto nuevo, PERO exigiendo su contraseña. Antes no se pedia: con
    mandar un email ajeno y una contraseña inventada se quedaba vinculado a la
    cuenta de otro.
    """
    exigir_password_valida(datos.password)

    email = normalizar_email(datos.email)

    with base_de_datos() as cursor:
        usuario = buscar_por_email(cursor, email)

        if usuario:
            if not verificar(datos.password, usuario["password"]):
                raise HTTPException(status_code=401, detail="Credenciales invalidas")

            usuario_id = usuario["id"]

        else:
            cursor.execute(
                """
                INSERT INTO usuarios
                (nombre, apellido, email, password)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    datos.nombre.strip(),
                    datos.apellido.strip(),
                    email,
                    hashear(datos.password)
                )
            )

            usuario_id = cursor.lastrowid

        cursor.execute(
            """
            SELECT usuario_id
            FROM usuario_proyecto
            WHERE usuario_id = %s
            AND proyecto_id = %s
            """,
            (
                usuario_id,
                datos.proyecto_id
            )
        )

        if cursor.fetchone():
            return {
                "ok": False,
                "mensaje": "El usuario ya está registrado en este proyecto",
                "usuario_id": usuario_id,
                "proyecto_id": datos.proyecto_id
            }

        cursor.execute(
            """
            INSERT INTO usuario_proyecto
            (usuario_id, proyecto_id)
            VALUES (%s, %s)
            """,
            (
                usuario_id,
                datos.proyecto_id
            )
        )

        return {
            "ok": True,
            "mensaje": "Usuario registrado correctamente",
            "usuario_id": usuario_id,
            "proyecto_id": datos.proyecto_id
        }


@app.get("/usuarios")
def listar_usuarios(authorization: str | None = Header(default=None)):
    """El padron completo. Pide `Authorization: Bearer <API_TOKEN>`.

    Nunca devuelve `password`: para validar credenciales esta POST /login.
    """
    exigir_token(authorization)

    with base_de_datos() as cursor:
        cursor.execute("""
            SELECT
                u.id,
                u.nombre,
                u.apellido,
                u.email,
                p.id AS proyecto_id,
                p.nombre AS proyecto
            FROM usuarios u
            LEFT JOIN usuario_proyecto up
                ON u.id = up.usuario_id
            LEFT JOIN proyectos p
                ON p.id = up.proyecto_id
            ORDER BY u.id, p.id
        """)

        resultados = cursor.fetchall()

    usuarios = {}

    for fila in resultados:

        usuario_id = fila["id"]

        if usuario_id not in usuarios:
            usuarios[usuario_id] = {
                "id": fila["id"],
                "nombre": fila["nombre"],
                "apellido": fila["apellido"],
                "email": fila["email"],
                "proyectos": []
            }

        if fila["proyecto_id"] is not None:
            usuarios[usuario_id]["proyectos"].append({
                "id": fila["proyecto_id"],
                "nombre": fila["proyecto"]
            })

    return list(usuarios.values())


@app.get("/proyectos")
def listar_proyectos():
    """Los proyectos a los que alguien se puede sumar.

    Sin token: es informacion publica y el formulario de alta la necesita para
    ofrecer la lista antes de que la persona tenga cuenta.
    """
    with base_de_datos() as cursor:
        cursor.execute("SELECT id, nombre FROM proyectos ORDER BY id")
        return cursor.fetchall()
