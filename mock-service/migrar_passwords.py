"""Hashea las contraseñas que quedaron en texto plano.

Se corre UNA vez, despues de actualizar el servicio. Es idempotente: saltea las
filas que ya empiezan con `$2` (el prefijo de bcrypt), asi que volver a
correrlo no hace nada y no rompe nada.

    docker compose exec mock-service python migrar_passwords.py

OJO: no tiene vuelta atras. Un hash no se puede convertir de nuevo en la
contraseña original, que es justamente el punto. Si te importa poder volver,
sacale un dump a la base antes:

    docker compose exec mysql mysqldump -uroot -proot registracion > respaldo.sql
"""
import os

import bcrypt
import mysql.connector


def conectar():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "registracion"),
        user=os.getenv("DB_USER", "registracion_user"),
        password=os.getenv("DB_PASSWORD", "registracion_pass")
    )


def main():
    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id, email, password FROM usuarios")
        usuarios = cursor.fetchall()

        hasheados = 0
        salteados = 0

        for usuario in usuarios:

            if usuario["password"].startswith("$2"):
                salteados += 1
                continue

            hash_nuevo = bcrypt.hashpw(
                usuario["password"].encode(),
                bcrypt.gensalt(rounds=12)
            ).decode()

            cursor.execute(
                "UPDATE usuarios SET password = %s WHERE id = %s",
                (hash_nuevo, usuario["id"])
            )

            print(f"  hasheada: {usuario['email']}")
            hasheados += 1

        # Los emails tambien se normalizan: el login busca en minusculas y en la
        # base hay filas cargadas como `Carnero@gmail.com`.
        cursor.execute("UPDATE usuarios SET email = LOWER(TRIM(email)) WHERE email <> LOWER(TRIM(email))")
        emails = cursor.rowcount

        conexion.commit()

        print(f"\nListo: {hasheados} hasheadas, {salteados} ya estaban, {emails} emails normalizados.")

    except Exception:
        conexion.rollback()
        raise

    finally:
        cursor.close()
        conexion.close()


if __name__ == "__main__":
    main()
