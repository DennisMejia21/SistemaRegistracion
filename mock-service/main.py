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
    """Crea la tabla de resets si falta, antes de atender el primer pedido.

    `database/init.sql` solo corre cuando el volumen de mysql esta vacio, asi
    que en una base que ya venia andando esa tabla no existiria. Aca se crea si
    hace falta y no pasa nada si ya esta.
    """
    asegurar_tabla_resets()
    yield


app = FastAPI(title="Servicio de Registración", lifespan=preparar)


# Token de las aplicaciones que leen el padrón (por ahora, el front de login).
# Va en `Authorization: Bearer`. Sin esto, GET /usuarios queda abierto y
# cualquiera que llegue al puerto se lleva todos los emails.
API_TOKEN = os.getenv("API_TOKEN", "")

# Token de la catedra, para emitir un reset de contraseña. Es OTRO token a
# proposito: el de arriba lo tiene cada front, y si sirviera para esto
# cualquier proyecto de la materia podria cambiarle la contraseña a cualquiera.
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


def asegurar_tabla_resets() -> None:
    """Tabla de los tokens de reset. Ver `database/init.sql`, que la crea igual.

    Del token guardamos el hash, no el token: si alguien se lleva un dump de la
    base, con los hashes no puede cambiarle la contraseña a nadie. Es SHA-256 y
    no bcrypt porque el token lo generamos nosotros con 256 bits de azar: no hay
    nada que adivinar a fuerza bruta, que es contra lo que sirve bcrypt.
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


def exigir_token(authorization: str | None) -> None:
    if not API_TOKEN:
        # Error de configuracion del servicio, no del que pide.
        raise HTTPException(status_code=500, detail="API_TOKEN no esta configurado")

    if not authorization or not secrets.compare_digest(authorization, f"Bearer {API_TOKEN}"):
        raise HTTPException(status_code=401, detail="Token invalido")


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
