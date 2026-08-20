# Sistema de Registración

Servicio de registración para los diferentes proyectos de Prácticas Profesionalizantes.

Es el **padrón** de la materia: acá viven las personas, sus contraseñas y la tabla que
dice a qué proyectos pertenece cada una. Los fronts de los proyectos no guardan
contraseñas: le preguntan a este servicio.

### Tecnologías

* Python
* FastAPI
* MySQL
* Docker
* Postman

### Funcionalidades

* Registrar usuarios.
* Asociar usuarios a proyectos.
* Evitar registros duplicados en un mismo proyecto.
* Validar credenciales (login).
* Consultar usuarios y los proyectos en los que están registrados.

### Endpoints

```text
GET  /             estado del servicio
POST /login        valida credenciales -> usuario + sus proyectos
POST /registrar    alta (o vinculación a otro proyecto)
GET  /usuarios     padrón completo          [requiere token]
GET  /proyectos    proyectos disponibles
```

#### `POST /login`

```json
{ "email": "lopez@gmail.com", "password": "Secreta123" }
```

Devuelve la persona con **todos** sus proyectos:

```json
{
  "id": 4,
  "nombre": "Fabian",
  "apellido": "Lopez",
  "email": "lopez@gmail.com",
  "proyectos": [
    { "id": 1, "nombre": "Carpooling" },
    { "id": 2, "nombre": "Alquiler de Quintas" }
  ]
}
```

Los proyectos van en la misma respuesta a propósito: con eso el front decide si no la
deja entrar (cero proyectos), si entra derecho (uno) o si le muestra un selector
(varios), sin un segundo pedido.

Si el email no existe o la contraseña no es la de esa cuenta responde **401** con
`{"detail": "Credenciales invalidas"}` — el mismo error en los dos casos, para que no
se pueda averiguar quién tiene cuenta y quién no.

#### `POST /registrar`

```json
{ "nombre": "Ema", "apellido": "Ortiz", "email": "ortiz@gmail.com",
  "password": "Secreta123", "proyecto_id": 3 }
```

Si el email **no existe**, crea la persona y la vincula al proyecto.

Si el email **ya existe**, no crea nada nuevo: verifica que la contraseña sea la de esa
cuenta y agrega el vínculo con el proyecto nuevo. Si la contraseña no coincide responde
401 y no toca nada. Así es como alguien que ya está en la materia se suma a un segundo
proyecto sin tener otra cuenta.

Si ya estaba en ese mismo proyecto responde 200 con `{"ok": false}`.

#### `GET /usuarios`

Devuelve el padrón completo, así que pide token:

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/usuarios
```

Sin el header, o con un token que no es, responde 401. **Nunca devuelve `password`**:
para validar credenciales está `POST /login`.

### Contraseñas

Se guardan hasheadas con **bcrypt** (cost 12). Entran en la columna `password`
(`VARCHAR(255)`) sin cambiar el esquema: un hash bcrypt son 60 caracteres.

bcrypt no mira más allá de los **72 bytes** de la contraseña, así que contraseñas más
largas se rechazan con 422. Ojo con confundir ese límite con el `VARCHAR(255)`: los 255
son para el hash, no para la contraseña.

Los emails se guardan y se buscan en minúsculas y sin espacios, para que el login no
dependa de cómo los escriban.

### Ejecutar

Las contraseñas de la base, el token y los puertos salen de un `.env` que **no está en
el repositorio**. Lo que se versiona es `.env.example`, con valores de mentira:

```bash
cp .env.example .env
```

Editalo (al menos `DB_PASSWORD`, `MYSQL_ROOT_PASSWORD` y `API_TOKEN`) y levantá:

```bash
docker compose up --build
```

Sin `.env` el `up` corta con `required variable DB_PASSWORD is missing a value`. Es a
propósito: así nadie levanta el padrón con la contraseña del ejemplo.

| Variable | Para qué | Por defecto |
|---|---|---|
| `DB_NAME`, `DB_USER` | base y usuario que crea mysql | `registracion`, `registracion_user` |
| `DB_PASSWORD` | contraseña de ese usuario, la misma de los dos lados | — (obligatoria) |
| `MYSQL_ROOT_PASSWORD` | root de mysql, para phpMyAdmin y los dumps | — (obligatoria) |
| `API_TOKEN` | token de `GET /usuarios` | — (obligatoria) |
| `PUERTO_API`, `PUERTO_MYSQL`, `PUERTO_PHPMYADMIN` | puertos **de la máquina** | `8000`, `3307`, `8081` |
| `BIND_HOST` | interfaz donde se publican | `127.0.0.1` (solo esta máquina) |

`DB_HOST` y `DB_PORT` no están en el `.env` a propósito: son los de la red interna de
compose (`mysql:3306`), no los de la máquina, y cambiarlos rompe el servicio.

Un token nuevo:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

API:

```text
http://localhost:8000
```

Documentación:

```text
http://localhost:8000/docs
```

phpMyAdmin queda en `http://localhost:8081` (o el `PUERTO_PHPMYADMIN` que hayas puesto).

### El front que lo consume

[login-pp2](https://github.com/Ficuu/login-pp2) es el front de login y alta. No tiene
base de datos ni guarda contraseñas: hace `POST /login` acá y, con los proyectos que
vuelven en esa respuesta, decide si la persona no entra (cero proyectos), entra derecho
(uno) o elige en un selector (varios).

Para probar los dos juntos, en el repo del front:

```bash
PADRON_URL=http://localhost:8000   # el PUERTO_API de acá
PADRON_TOKEN=...                   # el mismo API_TOKEN de acá
SESION_SECRETO=...                 # 32+ caracteres, propio del front
```

y levantarlo en otro puerto, `npm run dev -- -p 3001`.

### Migrar contraseñas viejas

Si la base ya tiene usuarios cargados de antes, sus contraseñas están en texto plano y
hay que hashearlas una sola vez:

```bash
docker compose exec mock-service python migrar_passwords.py
```

Es idempotente: saltea las filas que ya están hasheadas, así que correrlo dos veces no
hace nada. También normaliza los emails a minúsculas.

**No tiene vuelta atrás**: un hash no se puede convertir de nuevo en la contraseña
original, que es justamente el punto. Si querés poder volver, sacá un dump antes:

```bash
docker compose exec mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" registracion' > respaldo.sql
```

Mientras una fila no esté migrada, esa persona no puede entrar: su contraseña guardada
no es un hash válido y el login la rechaza.
