# Arquitectura de datos — App Anestesiólogos

La información se extrae de una **foto o PDF** de la orden quirúrgica y alimenta
una base de datos relacional (PostgreSQL) unida por llaves primarias/foráneas.
El esquema ejecutable está en [`db/schema.sql`](../db/schema.sql).

## Diagrama entidad-relación

```mermaid
erDiagram
    ANESTESIOLOGO ||--o{ DOCUMENTO_FUENTE : sube
    ANESTESIOLOGO ||--o{ CIRUGIA : atiende
    PACIENTE ||--o{ COBERTURA : tiene
    ASEGURADORA ||--o{ COBERTURA : otorga
    PACIENTE ||--o{ CIRUGIA : "se somete a"
    COBERTURA |o--o{ CIRUGIA : "paga"
    CLINICA ||--o{ CIRUGIA : "se realiza en"
    DOCUMENTO_FUENTE |o--o| CIRUGIA : "origina"
    CIRUGIA ||--|{ CIRUGIA_PROCEDIMIENTO : incluye
    PROCEDIMIENTO ||--o{ CIRUGIA_PROCEDIMIENTO : "se usa en"

    ANESTESIOLOGO {
        bigint anestesiologo_id PK
        varchar nombre
        varchar registro_medico
        varchar email
    }
    PACIENTE {
        bigint paciente_id PK
        varchar tipo_documento
        varchar numero_documento "Id (único con tipo)"
        varchar nombres
        varchar apellidos
    }
    ASEGURADORA {
        bigint aseguradora_id PK
        varchar nombre
        varchar nit
        varchar tipo "EPS | PREPAGADA | POLIZA"
    }
    COBERTURA {
        bigint cobertura_id PK
        bigint paciente_id FK
        bigint aseguradora_id FK
        varchar numero_poliza
        varchar plan
        boolean activa
    }
    CLINICA {
        bigint clinica_id PK
        varchar nombre
        varchar nit
        varchar ciudad
    }
    PROCEDIMIENTO {
        varchar codigo PK "CUPS"
        varchar nombre
    }
    DOCUMENTO_FUENTE {
        bigint documento_id PK
        bigint anestesiologo_id FK
        varchar tipo_archivo "IMAGEN | PDF"
        text url_archivo
        jsonb datos_extraidos
        numeric confianza
        varchar estado
    }
    CIRUGIA {
        bigint cirugia_id PK
        bigint paciente_id FK
        bigint cobertura_id FK "NULL = particular"
        bigint clinica_id FK
        bigint anestesiologo_id FK
        bigint documento_id FK
        date fecha_procedimiento
        varchar estado
    }
    CIRUGIA_PROCEDIMIENTO {
        bigint cirugia_id PK,FK
        varchar codigo PK,FK
        boolean es_principal
    }
```

## Tablas y decisiones de diseño

| Tabla | Qué guarda | Por qué así |
|---|---|---|
| `paciente` | Id (tipo + número de documento) y nombre | El documento es único: si el paciente vuelve, se reutiliza su registro. |
| `aseguradora` | EPS, prepagada o póliza (campo `tipo`) | Una sola tabla para los tres tipos; evita tres tablas casi iguales. |
| `cobertura` | Qué aseguradora tiene cada paciente y su nº de póliza/afiliación | Un paciente puede tener EPS **y** prepagada a la vez. |
| `clinica` | Dónde se hace el procedimiento | Catálogo reutilizable. |
| `procedimiento` | Catálogo de códigos CUPS + nombre | El código es la llave primaria natural. |
| `cirugia` | **Tabla central**: une paciente, cobertura, clínica, anestesiólogo y fecha | Cada foto/PDF genera un registro aquí. |
| `cirugia_procedimiento` | Códigos de una cirugía | Una orden suele traer varios códigos (ej. principal + adicional). |
| `documento_fuente` | Archivo original + JSON extraído por la IA | Trazabilidad: se puede revisar qué leyó la IA y corregir. |
| `anestesiologo` | Usuario de la app | Cada anestesiólogo ve solo sus cirugías. |

## Flujo: de la foto a la base de datos

```mermaid
flowchart LR
    A[Foto / PDF] --> B[documento_fuente<br/>estado = PENDIENTE]
    B --> C[IA extrae JSON]
    C --> D[Usuario revisa y confirma]
    D --> E{Upsert catálogos}
    E --> P[paciente]
    E --> AS[aseguradora → cobertura]
    E --> CL[clinica]
    E --> PR[procedimiento]
    P & AS & CL & PR --> F[cirugia + cirugia_procedimiento]
    F --> G[documento_fuente<br/>estado = VALIDADO]
```

### JSON que devuelve la extracción

```json
{
  "paciente":    { "tipo_documento": "CC", "numero_documento": "1020304050",
                   "nombres": "María Fernanda", "apellidos": "Gómez Ruiz" },
  "aseguradora": { "nombre": "Sura", "tipo": "PREPAGADA", "numero_poliza": "PP-778812" },
  "clinica":     { "nombre": "Clínica Las Américas", "ciudad": "Medellín" },
  "procedimientos": [
    { "codigo": "470100", "nombre": "Apendicectomía", "es_principal": true }
  ],
  "fecha_procedimiento": "2026-10-15",
  "confianza": 0.94
}
```

Cada bloque del JSON se mapea a una tabla: `paciente` → `paciente`,
`aseguradora` → `aseguradora` + `cobertura`, `clinica` → `clinica`,
`procedimientos[]` → `procedimiento` + `cirugia_procedimiento`, y la fecha → `cirugia`.
