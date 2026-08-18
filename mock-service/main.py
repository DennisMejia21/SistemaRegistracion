import os
import mysql.connector

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Servicio de Registración")


class Registro(BaseModel):
    nombre: str
    apellido: str
    email: str
    password: str
    proyecto_id: int


def conectar_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "registracion"),
        user=os.getenv("DB_USER", "registracion_user"),
        password=os.getenv("DB_PASSWORD", "registracion_pass")
    )


@app.get("/")
def inicio():
    return {
        "mensaje": "Servicio de registración funcionando"
    }


@app.post("/registrar")
def registrar(datos: Registro):

    conexion = conectar_db()
    cursor = conexion.cursor(dictionary=True)

    # Buscar si el usuario ya existe
    cursor.execute(
        "SELECT id FROM usuarios WHERE email = %s",
        (datos.email,)
    )

    usuario = cursor.fetchone()

    if usuario:
        usuario_id = usuario["id"]

    else:
        cursor.execute(
            """
            INSERT INTO usuarios
            (nombre, apellido, email, password)
            VALUES (%s, %s, %s, %s)
            """,
            (
                datos.nombre,
                datos.apellido,
                datos.email,
                datos.password
            )
        )

        usuario_id = cursor.lastrowid

    # Verificar si ya está registrado en el proyecto
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

    registro = cursor.fetchone()

    if registro:
        cursor.close()
        conexion.close()

        return {
            "ok": False,
            "mensaje": "El usuario ya está registrado en este proyecto",
            "usuario_id": usuario_id,
            "proyecto_id": datos.proyecto_id
        }

    # Registrar usuario en el proyecto
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

    conexion.commit()

    cursor.close()
    conexion.close()

    return {
        "ok": True,
        "mensaje": "Usuario registrado correctamente",
        "usuario_id": usuario_id,
        "proyecto_id": datos.proyecto_id
    }

@app.get("/usuarios")
def listar_usuarios():

    conexion = conectar_db()
    cursor = conexion.cursor(dictionary=True)

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
        ORDER BY u.id
    """)

    resultados = cursor.fetchall()

    cursor.close()
    conexion.close()

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