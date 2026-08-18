# Sistema de Registración

Servicio de registración para los diferentes proyectos de Prácticas Profesionalizantes.

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
* Consultar usuarios y los proyectos en los que están registrados.

### Endpoints

```text
POST /registrar
GET  /usuarios
```

### Ejecutar

```bash
docker compose up --build
```

API:

```text
http://localhost:8000
```

Documentación:

```text
http://localhost:8000/docs
```
