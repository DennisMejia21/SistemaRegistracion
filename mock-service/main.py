import hashlib
import os
import secrets
from contextlib import asynccontextmanager, contextmanager

import bcrypt
import mysql.connector

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


@asynccontextmanager
async def preparar(app: FastAPI):
    """Crea las tablas que falten antes de atender el primer pedido.

    `database/init.sql` solo corre cuando el volumen de mysql esta vacio, asi
    que en una base que ya venia andando esas tablas no existirian. Aca se
    crean si hace falta y no pasa nada si ya estan.
    """
    asegurar_tablas()
    yield


app = FastAPI(title="Servicio de Registración", lifespan=preparar)


# Token del login central, la unica aplicacion que ve el padron entero (lo
# necesita: muestra "elegi tu proyecto" antes de saber a cual va la persona).
# Va en `Authorization: Bearer`. Al arrancar se registra en `aplicaciones` con
# este valor; cambiarlo aca cambia el token de esa fila.
#
# Los proyectos NO usan este: cada uno tiene el suyo, que se crea con
# POST /aplicaciones y solo ve a su propia gente.
API_TOKEN = os.getenv("API_TOKEN", "")

# Como se llama esa fila en `aplicaciones`. Se busca por nombre para poder
# actualizarle el token cuando cambia API_TOKEN.
APP_DEL_LOGIN = "Login central"

# Token de la catedra: emite resets de contraseña y da de alta aplicaciones. Es
# OTRO token a proposito, y no esta en la tabla `aplicaciones`: los de ahi los
# tienen los fronts, y si alguno sirviera para esto, cualquier proyecto de la
# materia podria cambiarle la contraseña a cualquiera o emitirse tokens nuevos.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Cuanto vive un token de reset. Corto porque viaja por fuera del sistema
# (se lo pasan a la persona por donde puedan) y no hay forma de saber por
# cuantas manos anduvo.
MINUTOS_DE_RESET = int(os.getenv("MINUTOS_DE_RESET", "30"))

# bcrypt no mira mas alla de los 72 bytes de la contraseña. Es un limite del
# algoritmo, no de la columna: `password` es VARCHAR(255) porque ahi entra el
# hash (60 caracteres), no porque la contraseña pueda ser tan larga.
PASSWORD_MAX_BYTES = 72

# El front ya pide 8; que el padron acepte menos no tendria sentido, porque el
# alta y el reset se le pueden pegar directo sin pasar por ningun front.
PASSWORD_MIN_LARGO = 8


class Registro(BaseModel):
    nombre: str
    apellido: str
    email: str
    password: str
    proyecto_id: int


class Credenciales(BaseModel):
    email: str
    password: str


class PedidoDeReset(BaseModel):
    email: str


class PasswordNueva(BaseModel):
    token: str
    password: str


class AplicacionNueva(BaseModel):
    nombre: str
    # None = ve el padron entero. Es para el login central, no para un proyecto.
    proyecto_id: int | None = None


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


def asegurar_tablas() -> None:
    """Tablas que no estan en el init.sql original. Ver `database/init.sql`.

    De los tokens guardamos el hash, no el token: si alguien se lleva un dump de
    la base, con los hashes no entra a ningun lado ni le cambia la contraseña a
    nadie. Es SHA-256 y no bcrypt porque los generamos nosotros con 256 bits de
    azar: no hay nada que adivinar a fuerza bruta, que es contra lo que sirve
    bcrypt.
    """
    with base_de_datos() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resets_password (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                token_hash CHAR(64) NOT NULL UNIQUE,
                vence_en DATETIME NOT NULL,
                usado_en DATETIME NULL,

                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS aplicaciones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL UNIQUE,
                proyecto_id INT NULL,
                token_hash CHAR(64) NOT NULL UNIQUE,
                creada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revocada_en DATETIME NULL,

                FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)
            )
            """
        )

        asegurar_app_del_login(cursor)


def asegurar_app_del_login(cursor) -> None:
    """Registra el token de API_TOKEN como la aplicacion del login central.

    Existe para no romper lo que ya andaba: hasta ahora el token vivia solo en
    el entorno. Ahora los tokens viven en la tabla, y este se sincroniza desde
    la variable, asi cambiarla en el `.env` sigue alcanzando.
    """
    if not API_TOKEN:
        return

    token_hash = hashear_token(API_TOKEN)

    cursor.execute(
        "SELECT id, token_hash FROM aplicaciones WHERE nombre = %s",
        (APP_DEL_LOGIN,)
    )

    fila = cursor.fetchone()

    if fila is None:
        cursor.execute(
            """
            INSERT INTO aplicaciones
            (nombre, proyecto_id, token_hash)
            VALUES (%s, NULL, %s)
            """,
            (APP_DEL_LOGIN, token_hash)
        )

    elif fila["token_hash"] != token_hash:
        cursor.execute(
            """
            UPDATE aplicaciones
            SET token_hash = %s, revocada_en = NULL
            WHERE id = %s
            """,
            (token_hash, fila["id"])
        )


def hashear_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def exigir_password_valida(password: str) -> None:
    if len(password) < PASSWORD_MIN_LARGO:
        raise HTTPException(
            status_code=422,
            detail=f"La contraseña necesita al menos {PASSWORD_MIN_LARGO} caracteres"
        )

    if len(password.encode()) > PASSWORD_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"La contraseña no puede pasar de {PASSWORD_MAX_BYTES} bytes"
        )


def aplicacion_del_token(cursor, authorization: str | None) -> dict:
    """Devuelve la aplicacion dueña del `Authorization: Bearer`, o corta con 401.

    Antes habia un solo token, en el entorno, y valia para todo: con el, el
    front de cualquier proyecto se llevaba el padron entero, incluida la gente
    de los otros. Ahora cada proyecto tiene el suyo y el padron sabe QUIEN
    pregunta, asi que puede devolverle solo lo suyo.

    Se busca por el hash del token y no se compara nada a mano: el token son
    256 bits de azar, no hay nada que adivinar probando de a poco.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token invalido")

    cursor.execute(
        """
        SELECT id, nombre, proyecto_id
        FROM aplicaciones
        WHERE token_hash = %s
        AND revocada_en IS NULL
        """,
        (hashear_token(authorization.removeprefix("Bearer ").strip()),)
    )

    aplicacion = cursor.fetchone()

    if aplicacion is None:
        raise HTTPException(status_code=401, detail="Token invalido")

    return aplicacion


def exigir_admin(authorization: str | None) -> None:
    """El token de la catedra, no el de las aplicaciones."""
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN no esta configurado")

    if ADMIN_TOKEN == API_TOKEN:
        # Si fueran el mismo, el token que tiene cada front alcanzaria para
        # resetear contraseñas ajenas. Mejor no arrancar que dejarlo pasar.
        raise HTTPException(
            status_code=500,
            detail="ADMIN_TOKEN no puede ser igual a API_TOKEN"
        )

    if not authorization or not secrets.compare_digest(authorization, f"Bearer {ADMIN_TOKEN}"):
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
    """Los usuarios que le corresponden a la aplicacion que pregunta.

    Pide `Authorization: Bearer <token de la aplicacion>`. Si ese token es el de
    un proyecto, devuelve solo a los inscriptos en ESE proyecto, y de cada uno
    solo ese proyecto: que alguien este ademas en Carpooling no es asunto de
    Alquiler de Quintas. El unico que ve el padron entero es el login central,
    porque tiene que ofrecer "elegi tu proyecto" antes de saber a cual va.

    Nunca devuelve `password`: para validar credenciales esta POST /login.
    """
    with base_de_datos() as cursor:
        aplicacion = aplicacion_del_token(cursor, authorization)

        if aplicacion["proyecto_id"] is None:
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

        else:
            # JOIN y no LEFT JOIN: aca las filas sin proyecto sobran, porque la
            # condicion para aparecer es justamente estar en este proyecto.
            cursor.execute(
                """
                SELECT
                    u.id,
                    u.nombre,
                    u.apellido,
                    u.email,
                    p.id AS proyecto_id,
                    p.nombre AS proyecto
                FROM usuarios u
                JOIN usuario_proyecto up
                    ON u.id = up.usuario_id
                    AND up.proyecto_id = %s
                JOIN proyectos p
                    ON p.id = up.proyecto_id
                ORDER BY u.id
                """,
                (aplicacion["proyecto_id"],)
            )

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


@app.post("/password/reset")
def emitir_reset(datos: PedidoDeReset, authorization: str | None = Header(default=None)):
    """Emite un token de un solo uso para que alguien elija contraseña nueva.

    Pide `Authorization: Bearer <ADMIN_TOKEN>`, que es el de la catedra y NO el
    que tienen los fronts: quien pide un reset esta diciendo "esta persona es
    quien dice ser", y eso lo comprueba alguien de la materia por fuera del
    sistema (la ve, la conoce, le pregunta algo). El servicio no tiene con que
    comprobarlo: no manda mails.

    El token se devuelve UNA vez y despues no se puede volver a ver, porque en
    la base queda solo su hash. Hay que hacerselo llegar a la persona por donde
    sea, y por eso vive poco.
    """
    exigir_admin(authorization)

    email = normalizar_email(datos.email)

    with base_de_datos() as cursor:
        usuario = buscar_por_email(cursor, email)

        if usuario is None:
            # Aca si se puede decir que no existe: del otro lado hay alguien de
            # la catedra, no cualquiera. Que se entere de que se equivoco de
            # email es mejor que emitir un token para nadie.
            raise HTTPException(status_code=404, detail="No hay nadie con ese email")

        # Un pedido nuevo invalida los anteriores: si no, cada uno que se emitio
        # y quedo dando vueltas sigue sirviendo hasta que vence.
        cursor.execute(
            """
            UPDATE resets_password
            SET usado_en = NOW()
            WHERE usuario_id = %s
            AND usado_en IS NULL
            """,
            (usuario["id"],)
        )

        token = secrets.token_urlsafe(32)

        cursor.execute(
            """
            INSERT INTO resets_password
            (usuario_id, token_hash, vence_en)
            VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s MINUTE))
            """,
            (
                usuario["id"],
                hashear_token(token),
                MINUTOS_DE_RESET
            )
        )

        cursor.execute(
            "SELECT vence_en FROM resets_password WHERE id = %s",
            (cursor.lastrowid,)
        )

        return {
            "token": token,
            "email": usuario["email"],
            "vence_en": cursor.fetchone()["vence_en"],
            "minutos": MINUTOS_DE_RESET
        }


@app.post("/password")
def cambiar_password(datos: PasswordNueva):
    """Canjea el token por una contraseña nueva. La elige la persona.

    Sin token: el token ES la credencial. Por eso el mismo error para uno
    inventado, uno vencido y uno ya usado: no hay nada que averiguar probando.

    Las sesiones que el front haya abierto antes siguen vivas: las emite el
    front, no este servicio, y aca no hay nada que revocar.
    """
    exigir_password_valida(datos.password)

    with base_de_datos() as cursor:
        cursor.execute(
            """
            SELECT id, usuario_id
            FROM resets_password
            WHERE token_hash = %s
            AND usado_en IS NULL
            AND vence_en > NOW()
            """,
            (hashear_token(datos.token),)
        )

        reset = cursor.fetchone()

        if reset is None:
            raise HTTPException(status_code=400, detail="El token no sirve o ya vencio")

        cursor.execute(
            "UPDATE usuarios SET password = %s WHERE id = %s",
            (
                hashear(datos.password),
                reset["usuario_id"]
            )
        )

        # Se marca usado en la misma transaccion que el cambio: o pasan las dos
        # cosas o no pasa ninguna, asi el token no puede quedar servido dos veces.
        cursor.execute(
            "UPDATE resets_password SET usado_en = NOW() WHERE id = %s",
            (reset["id"],)
        )

        return {
            "ok": True,
            "mensaje": "Contraseña actualizada"
        }


@app.post("/aplicaciones")
def crear_aplicacion(datos: AplicacionNueva, authorization: str | None = Header(default=None)):
    """Da de alta una aplicacion y le emite su token. Solo la catedra.

    Una por proyecto: asi el padron sabe quien le pregunta y cada uno ve solo a
    su gente. Si una filtra su token, se revoca esa sola y los demas siguen
    andando; con el token unico de antes habia que cambiarlo en todos.

    El token se ve UNA vez, aca. En la base queda solo su hash.
    """
    exigir_admin(authorization)

    nombre = datos.nombre.strip()

    if not nombre:
        raise HTTPException(status_code=422, detail="La aplicacion necesita un nombre")

    with base_de_datos() as cursor:
        if datos.proyecto_id is not None:
            cursor.execute("SELECT id FROM proyectos WHERE id = %s", (datos.proyecto_id,))

            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Ese proyecto no existe")

        cursor.execute("SELECT id FROM aplicaciones WHERE nombre = %s", (nombre,))

        if cursor.fetchone():
            raise HTTPException(status_code=409, detail="Ya hay una aplicacion con ese nombre")

        token = secrets.token_urlsafe(32)

        cursor.execute(
            """
            INSERT INTO aplicaciones
            (nombre, proyecto_id, token_hash)
            VALUES (%s, %s, %s)
            """,
            (
                nombre,
                datos.proyecto_id,
                hashear_token(token)
            )
        )

        return {
            "id": cursor.lastrowid,
            "nombre": nombre,
            "proyecto_id": datos.proyecto_id,
            "token": token,
            "aviso": "Guardalo ahora: no se vuelve a mostrar"
        }


@app.get("/aplicaciones")
def listar_aplicaciones(authorization: str | None = Header(default=None)):
    """Que aplicaciones hay y que ve cada una. Nunca los tokens: no los tenemos."""
    exigir_admin(authorization)

    with base_de_datos() as cursor:
        cursor.execute(
            """
            SELECT
                a.id,
                a.nombre,
                a.proyecto_id,
                p.nombre AS proyecto,
                a.creada_en,
                a.revocada_en
            FROM aplicaciones a
            LEFT JOIN proyectos p ON p.id = a.proyecto_id
            ORDER BY a.id
            """
        )

        return cursor.fetchall()


@app.delete("/aplicaciones/{aplicacion_id}")
def revocar_aplicacion(aplicacion_id: int, authorization: str | None = Header(default=None)):
    """Deja de aceptar el token de esa aplicacion. No se borra la fila: queda el
    registro de que existio y cuando se corto."""
    exigir_admin(authorization)

    with base_de_datos() as cursor:
        cursor.execute(
            "SELECT id, nombre, revocada_en FROM aplicaciones WHERE id = %s",
            (aplicacion_id,)
        )

        aplicacion = cursor.fetchone()

        if aplicacion is None:
            raise HTTPException(status_code=404, detail="No existe esa aplicacion")

        if aplicacion["nombre"] == APP_DEL_LOGIN:
            # Revocarla dejaria al login sin entrar, y al reiniciar el servicio
            # volveria igual desde API_TOKEN: se cambia ahi, no por aca.
            raise HTTPException(
                status_code=409,
                detail="La aplicacion del login se maneja con API_TOKEN"
            )

        if aplicacion["revocada_en"] is None:
            cursor.execute(
                "UPDATE aplicaciones SET revocada_en = NOW() WHERE id = %s",
                (aplicacion_id,)
            )

        return {
            "ok": True,
            "mensaje": f"La aplicacion {aplicacion['nombre']} ya no entra"
        }
