from app.modelos import OrdenConfirmada


def orden(**cambios) -> OrdenConfirmada:
    base = {
        "paciente": {"tipo_documento": "CC", "numero_documento": "1.020.304.050",
                     "nombres": "María Fernanda", "apellidos": "Gómez Ruiz"},
        "aseguradora": {"nombre": "Sura", "tipo": "EPS", "numero_poliza": None, "plan": None},
        "clinica": {"nombre": "Clínica Las Américas", "ciudad": "Medellín"},
        "procedimientos": [{"codigo": "471100", "nombre": "Apendicectomía", "es_principal": False}],
        "fecha_procedimiento": "2026-10-15",
    }
    base.update(cambios)
    return OrdenConfirmada.model_validate(base)
