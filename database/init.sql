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
