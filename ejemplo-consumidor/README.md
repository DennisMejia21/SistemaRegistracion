# Ejemplo: un proyecto que usa el padrón

Esto es lo que tiene que hacer el front de un proyecto de la materia (Carpooling,
Alquiler de Quintas, Sistema de Reservas) para que su gente entre con la cuenta de PP2.

Son **dos cosas**. Nada más:

1. Mandar a la persona al login central:
   `https://login.pp2/entrar?proyecto_id=1&state=algoAlAzar`
2. Cuando vuelve a tu URL con `?codigo=...`, canjear ese código:

```js
const r = await fetch(`${PADRON_URL}/codigos/canjear`, {
  method: "POST",
  headers: { "Content-Type": "application/json",
             Authorization: `Bearer ${PADRON_TOKEN}` },
  body: JSON.stringify({ codigo }),
});

if (!r.ok) return rechazar();          // inválido, vencido, usado o de otro proyecto

const { usuario } = await r.json();    // { id, nombre, apellido, email }
// y acá emitís TU sesión, como la tengas hecha
```

**Tu proyecto nunca ve una contraseña.** Ni la pide, ni la guarda, ni la recibe. Si en
algún momento estás escribiendo un formulario de contraseña, algo se desvió.

[`consumidor.py`](consumidor.py) es eso mismo, andando, en Python con biblioteca
estándar y sin dependencias: no está en Python porque tengas que usar Python, sino para
que se lea como lo que es —dos pedidos HTTP— y lo traduzcas a lo que uses.

## Probarlo

Con el padrón levantado (`docker compose up -d --build` en la raíz) y el login central
en el 3001:

```bash
# 1. La cátedra da de alta tu proyecto y te pasa el token (se ve una sola vez)
curl -X POST localhost:8000/aplicaciones \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"nombre":"Front Carpooling","proyecto_id":1}'

# 2. Y le dice al padrón dónde vive tu proyecto, que es a donde va a volver la persona
curl -X PUT localhost:8000/proyectos/1/url \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"url":"http://127.0.0.1:9001/sesion"}'

# 3. Levantás esto
docker build -t ejemplo-consumidor ejemplo-consumidor
docker run --rm -p 127.0.0.1:9001:9000 \
  --network sistemaregistracion_default \
  -e PADRON_URL=http://mock-service:8000 \
  -e PADRON_TOKEN="el-token-del-paso-1" \
  -e LOGIN_URL=http://127.0.0.1:3001 \
  -e PROYECTO_ID=1 \
  ejemplo-consumidor
```

Y entrás a `http://127.0.0.1:9001`.

## Las variables

| Variable | Qué es |
|---|---|
| `PADRON_URL` | El padrón, para los pedidos **servidor a servidor**. Puede ser un nombre interno de docker. |
| `PADRON_TOKEN` | El token de **tu** proyecto. Nunca lo mandes al navegador. |
| `LOGIN_URL` | El login central. Esta la abre el **navegador** de la persona, así que tiene que ser alcanzable desde su máquina. |
| `PROYECTO_ID` | Cuál sos, según la tabla `proyectos`. |

`PADRON_URL` y `LOGIN_URL` son distintas por eso: una la usa tu servidor, la otra la usa
el navegador. Es el error más fácil de cometer acá.

## El `state`

El valor al azar que mandás en `/entrar?...&state=` vuelve tal cual en la query. Guardalo
antes de mandar a la persona (cookie, sesión, lo que uses) y comparalo cuando vuelve: si
no coincide, es una vuelta que vos nunca empezaste y no hay que aceptarla. El login no lo
mira ni lo usa: es tuyo.

## Los errores que vas a ver

| Qué pasó | Respuesta de `/codigos/canjear` |
|---|---|
| Código inventado, vencido, ya usado o de otro proyecto | `400 {"detail": "El codigo no sirve o ya vencio"}` |
| Tu token no es, o la cátedra lo revocó | `401 {"detail": "Token invalido"}` |
| Estás usando el token del login central en vez del tuyo | `403` |

Los códigos duran **60 segundos** y sirven **una sola vez**. Si estás depurando y
recargás la página de vuelta, el segundo intento falla: es lo esperado, pedí uno nuevo
entrando de nuevo.
