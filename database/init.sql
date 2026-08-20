CREATE TABLE usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(50) NOT NULL,
    apellido VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL
);

CREATE TABLE proyectos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL
);

CREATE TABLE usuario_proyecto (
    usuario_id INT NOT NULL,
    proyecto_id INT NOT NULL,

    PRIMARY KEY (usuario_id, proyecto_id),

    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)
);

INSERT INTO proyectos (nombre) VALUES
('Carpooling'),
('Alquiler de Quintas'),
('Sistema de Reservas');


-- Tokens de reset de contraseña (POST /password/reset).
--
-- Se guarda el hash del token, no el token: con un dump de la base no se le
-- puede cambiar la contraseña a nadie. `usado_en` marca los canjeados y los
-- que quedaron invalidados por un pedido posterior.
--
-- El servicio la crea igual al arrancar si no existe, para las bases que ya
-- venian andando: este archivo solo corre con el volumen de mysql vacio.
CREATE TABLE IF NOT EXISTS resets_password (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    vence_en DATETIME NOT NULL,
    usado_en DATETIME NULL,

    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

-- Aplicaciones que le pegan al padrón: el login central y el front de cada
-- proyecto. Cada una tiene su token, para que el padrón sepa quién pregunta y
-- le devuelva solo lo suyo (ver GET /usuarios).
--
-- `proyecto_id` NULL = ve el padrón entero. Es el login central, que tiene que
-- ofrecer "elegí tu proyecto" antes de saber a cuál va la persona.
--
-- Del token se guarda el hash, no el token. Se dan de alta con
-- POST /aplicaciones, con el token de la cátedra.
CREATE TABLE IF NOT EXISTS aplicaciones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    proyecto_id INT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    creada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revocada_en DATETIME NULL,

    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)
);
