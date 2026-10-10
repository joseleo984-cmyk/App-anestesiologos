-- Anestesiólogo inicial mientras no hay inicio de sesión (ANESTESIOLOGO_ID=1)
INSERT INTO anestesiologo (anestesiologo_id, nombre, email)
VALUES (1, 'Anestesiólogo', 'anestesiologo@ejemplo.com')
ON CONFLICT (anestesiologo_id) DO NOTHING;
SELECT setval('anestesiologo_anestesiologo_id_seq', GREATEST((SELECT MAX(anestesiologo_id) FROM anestesiologo), 1));
