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
* Resetear la contraseña de alguien que la perdió.
* Mandar a cada persona a la plataforma de su proyecto, sin que esa plataforma
  vea nunca su contraseña.
* Consultar usuarios y los proyectos en los que están registrados.

### Endpoints

```text
GET  /                 estado del servicio
POST /login            valida credenciales -> usuario + sus proyectos
POST /registrar        alta (o vinculación a otro proyecto)
GET  /usuarios         los usuarios de quien pregunta  [token de app]
GET  /proyectos        proyectos disponibles
POST /password/reset   emite un token de reset       [token de la cátedra]
POST /password         canjea el token por una contraseña nueva
POST /aplicaciones     da de alta una app y su token   [token de la cátedra]
GET  /aplicaciones     qué apps hay y qué ve cada una  [token de la cátedra]
DELETE /aplicaciones/{id}   revoca el token de una app [token de la cátedra]
PUT  /proyectos/{id}/url    dónde vive ese proyecto   [token de la cátedra]
POST /codigos          emite un código de ingreso    [token del login central]
POST /codigos/canjear  código -> quién es la persona [token del proyecto]
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

Devuelve **los usuarios que le corresponden a la aplicación que pregunta**, según su
token:

```bash
curl -H "Authorization: Bearer $TOKEN_DE_LA_APP" http://localhost:8000/usuarios
```

Si el token es el de un proyecto, salen solo los inscriptos en **ese** proyecto, y de
cada uno solo ese proyecto: que alguien esté además en Carpooling no es asunto de
Alquiler de Quintas. El único que ve el padrón entero es el login central, que lo
necesita para ofrecer "elegí tu proyecto" antes de saber a cuál va la persona.

Sin el header, con un token que no es, o con uno revocado, responde 401. **Nunca
devuelve `password`**: para validar credenciales está `POST /login`.

### Un token por proyecto

Cada aplicación que le pega al padrón tiene el suyo, en la tabla `aplicaciones`. Antes
había uno solo para todos, y con él cualquier front se llevaba el padrón entero,
incluida la gente de los otros proyectos. Ahora el padrón sabe **quién** pregunta.

Las da de alta la cátedra, con su `ADMIN_TOKEN`:

```bash
curl -X POST localhost:8000/aplicaciones \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"nombre":"Carpooling","proyecto_id":1}'
```

```json
{ "id": 2, "nombre": "Carpooling", "proyecto_id": 1,
  "token": "d-Bz-m38gy7YhvWs4BP-MvwDfzmQrWMOS5tQwnyyBkM",
  "aviso": "Guardalo ahora: no se vuelve a mostrar" }
```

Ese token es el que va en el `.env` del front de ese proyecto. **Se ve una sola vez**:
en la base queda solo su hash, así que un dump no le sirve a nadie para entrar. Si se
pierde, se revoca esa y se crea otra.

Para ver qué hay y cortar una:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/aplicaciones
curl -X DELETE -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/aplicaciones/2
```

Revocar no borra la fila: queda el registro de que existió y cuándo se cortó, y no toca
a las demás.

**El login central es un caso aparte.** Su token es `API_TOKEN`, del `.env`, y el
servicio registra esa aplicación solo al arrancar (`proyecto_id` NULL, o sea: ve todo).
Cambiar la variable y reiniciar cambia su token; por eso esa fila no se revoca desde la
API, se maneja desde el `.env`.

`ADMIN_TOKEN` no está en esta tabla y no es el token de ninguna aplicación: si lo fuera,
cualquier proyecto podría emitirse tokens nuevos o resetear contraseñas ajenas.

### Entrar a un proyecto

Cada proyecto de la materia tiene su propia plataforma, y la persona entra **una vez**,
en el login central. Después el login la manda a su proyecto con un código de un solo
uso, y ese proyecto lo canjea acá para enterarse de quién es. **Ningún proyecto ve una
contraseña ni guarda una.**

El circuito arranca en cualquiera de los dos lados:

* **Desde el proyecto** (el caso normal): Carpooling tiene un botón "Ingresar" que manda
  a `https://login.pp2/entrar?proyecto_id=1&state=algoAlAzar`. La persona se identifica
  y vuelve. Si ya tenía sesión abierta en el login, vuelve sin que le pregunten nada.
* **Desde el login**: entra al login central y elige su proyecto en el selector.

De ahí en adelante es lo mismo:

```text
1. La persona queda identificada y se sabe a qué proyecto va.

2. El login pide el código:
   POST /codigos  {"usuario_id": 1, "proyecto_id": 1}   [token del login]
   -> {"codigo": "NCicTX...", "volver_a": "https://carpooling.../sesion", "segundos": 60}

3. El navegador va a  https://carpooling.../sesion?codigo=NCicTX...&state=...

4. El backend de Carpooling canjea:
   POST /codigos/canjear  {"codigo": "NCicTX..."}       [token de Carpooling]
   -> {"usuario": {"id": 1, "nombre": "Ema", "apellido": "Ortiz",
                   "email": "ortiz@gmail.com"},
       "proyecto": {"id": 1, "nombre": "Carpooling"}}

5. Carpooling emite SU sesión con eso. Listo.
```

Antes de que ande, la cátedra tiene que decir dónde vive cada proyecto:

```bash
curl -X PUT localhost:8000/proyectos/1/url \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"url":"https://carpooling.../sesion"}'
```

Esa URL es **la que ve el navegador**, no el nombre del contenedor: el redirect lo hace
el navegador de la persona, no el servidor.

**Hay un ejemplo andando** en [`ejemplo-consumidor/`](ejemplo-consumidor): un proyecto de
juguete, sin dependencias, con el botón "Ingresar", la vuelta y el canje. Se levanta con
un `docker run` y sirve para copiar.

Lo que tiene que escribir cada equipo es el paso 4, y es esto:

```js
// GET /sesion?codigo=...
const r = await fetch(`${process.env.PADRON_URL}/codigos/canjear`, {
  method: "POST",
  headers: { "Content-Type": "application/json",
             Authorization: `Bearer ${process.env.PADRON_TOKEN}` },
  body: JSON.stringify({ codigo }),
});

if (!r.ok) return respuestaDeError();       // código inválido, vencido o ajeno

const { usuario } = await r.json();         // ya está: es esta persona
// y acá cada uno emite su propia sesión, como la tenga hecha
```

Por qué está armado así:

* **El destino sale de `proyectos.url`, nunca del pedido.** Si el que pide el código
  pudiera elegir a dónde mandarlo, se mandaría el código de otra persona a un sitio
  propio y entraría como ella. Por eso la URL la fija la cátedra y no viaja en la query.
* **Solo el login central emite códigos.** Emitir uno es afirmar "esta persona ya probó
  quién es", y el único que valida contraseñas es el login. Si el front de Carpooling
  pudiera emitirlos, se emitiría uno para cualquiera y entraría sin saber su contraseña.
* **Un código solo lo canjea el proyecto al que va.** Con el token de Carpooling no se
  canjea un código de Alquiler de Quintas.
* **Un solo uso y 60 segundos** (`SEGUNDOS_DE_CODIGO`). Solo tiene que sobrevivir un
  redirect; cuanto menos vive, menos importa que quede escrito en el historial del
  navegador o en el log de algún servidor. Pedir uno nuevo invalida el anterior.
* **Mismo error para todo**: inventado, vencido, usado o de otro proyecto responden 400
  con `{"detail": "El codigo no sirve o ya vencio"}`.
* **Sin URL no hay salto.** Si un proyecto todavía no tiene plataforma, `POST /codigos`
  responde 409 y el login deja a la persona en su propia pantalla. Los proyectos se van
  sumando de a uno, sin romper a los demás.
* **El `state` es del proyecto.** Lo manda él al empezar y le vuelve tal cual; ni el
  login ni el padrón lo miran. Sirve para que el proyecto reconozca su propia ida y no
  acepte una vuelta que nunca empezó.

### Contraseñas

Se guardan hasheadas con **bcrypt** (cost 12). Entran en la columna `password`
(`VARCHAR(255)`) sin cambiar el esquema: un hash bcrypt son 60 caracteres.

Tiene que tener **al menos 8 caracteres**, y bcrypt no mira más allá de los **72
bytes**, así que las más largas se rechazan con 422. Ojo con confundir ese límite con el
`VARCHAR(255)`: los 255 son para el hash, no para la contraseña.

Los emails se guardan y se buscan en minúsculas y sin espacios, para que el login no
dependa de cómo los escriban.

### Reset de contraseña

No hay "olvidé mi contraseña" automático: el servicio no manda mails, así que no tiene
forma de comprobar que quien pide el reset sea la persona. Eso lo comprueba alguien de
la cátedra por fuera del sistema, y recién entonces emite un token.

Son dos pasos. Primero la cátedra pide el token, con **su** `ADMIN_TOKEN`:

```bash
curl -X POST localhost:8000/password/reset \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"email":"ortiz@gmail.com"}'
```

```json
{ "token": "XyK5xoKB0yPebLrXKD_e8hrVBsXrR14Qoe3QRo2vpqM",
  "email": "ortiz@gmail.com", "vence_en": "2026-08-20T03:09:12", "minutos": 30 }
```

Ese token **se ve una sola vez**: en la base queda solo su hash. Hay que hacérselo
llegar a la persona por donde sea (mensaje, en mano). Después lo canjea ella, eligiendo
su contraseña, sin que nadie más la conozca:

```bash
curl -X POST localhost:8000/password -H 'Content-Type: application/json' \
  -d '{"token":"XyK5...","password":"LaQueEllaElija"}'
```

Detalles que importan:

* **`ADMIN_TOKEN` no es el `API_TOKEN`.** El `API_TOKEN` lo tiene cada front de la
  materia; si sirviera para esto, cualquier proyecto podría cambiarle la contraseña a
  cualquiera. Si los dos valores son iguales, el servicio se niega a emitir resets.
* **Un solo uso y 30 minutos** (`MINUTOS_DE_RESET`). Pedir uno nuevo invalida el
  anterior.
* **Mismo error para todo**: token inventado, vencido o ya usado responden 400 con
  `{"detail": "El token no sirve o ya vencio"}`. No hay nada que averiguar probando.
* **Las sesiones abiertas no se cortan.** Las emite el front (cookie firmada, 24 h) y
  este servicio no tiene con qué revocarlas. Si el reset fue porque alguien se metió en
  la cuenta, además hay que esperar a que venza esa cookie o cambiar el
  `SESION_SECRETO` del front, que cierra todas.
* La tabla `resets_password` la crea `database/init.sql`, y el servicio la crea también
  al arrancar si no existe: `init.sql` solo corre con el volumen de mysql vacío, y las
  bases que ya venían andando no la tendrían.

### Ejecutar

Las contraseñas de la base, el token y los puertos salen de un `.env` que **no está en
el repositorio**. Lo que se versiona es `.env.example`, con valores de mentira:

```bash
cp .env.example .env
```

Editalo (al menos `DB_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `API_TOKEN` y `ADMIN_TOKEN`) y
levantá:

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
| `API_TOKEN` | token del **login central**, la app que ve todo el padrón | — (obligatoria) |
| `ADMIN_TOKEN` | token de la cátedra: resets y alta de aplicaciones | — (obligatoria) |
| `MINUTOS_DE_RESET` | cuánto vive un token de reset | `30` |
| `SEGUNDOS_DE_CODIGO` | cuánto vive un código de ingreso a un proyecto | `60` |
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

### Los fronts que lo consumen

[login-pp2](https://github.com/Ficuu/login-pp2) es el login central de la materia. No
tiene base de datos ni guarda contraseñas: hace `POST /login` acá y, con los proyectos
que vuelven en esa respuesta, decide si la persona no entra (cero proyectos), entra
derecho (uno) o elige en un selector (varios). Usa el token de `API_TOKEN`, que es el
único que ve el padrón entero.

Para probar los dos juntos, en el repo del front:

```bash
cp .env.example .env    # PADRON_TOKEN = el API_TOKEN de acá, y un SESION_SECRETO
docker compose up -d --build
```

Queda en `http://localhost:3001`. Levantá este repo primero: el compose del front se
cuelga de la red que crea el de acá.

El front de **cada proyecto** (Carpooling, Alquiler de Quintas, Sistema de Reservas) no
usa ese token: cada uno tiene el suyo, dado de alta con `POST /aplicaciones`, y con él
solo ve a su propia gente. Ver [Un token por proyecto](#un-token-por-proyecto).

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
