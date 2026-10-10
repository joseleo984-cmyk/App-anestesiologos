"""Modelos de datos.

OrdenExtraida: lo que la IA lee de la foto/PDF. Todo es opcional porque la
orden puede estar incompleta o ilegible.
OrdenConfirmada: lo que el usuario confirma en pantalla. Exige lo mínimo para
crear la cirugía en la base de datos.
"""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

TipoDocumento = Literal["CC", "TI", "CE", "RC", "PA", "PPT", "MS", "AS"]
TipoAseguradora = Literal["EPS", "PREPAGADA", "POLIZA"]
EstadoCirugia = Literal["PROGRAMADA", "REALIZADA", "CANCELADA", "FACTURADA", "PAGADA"]


def _limpiar(v):
    if isinstance(v, str):
        v = " ".join(v.split())
        return v or None
    return v


class _Base(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _quitar_espacios(cls, v):
        return _limpiar(v)


# ---------------------------------------------------------------- extracción
class PacienteExtraido(_Base):
    tipo_documento: Optional[TipoDocumento] = None
    numero_documento: Optional[str] = None
    nombres: Optional[str] = None
    apellidos: Optional[str] = None


class AseguradoraExtraida(_Base):
    nombre: Optional[str] = None
    tipo: Optional[TipoAseguradora] = None
    numero_poliza: Optional[str] = None
    plan: Optional[str] = None


class ClinicaExtraida(_Base):
    nombre: Optional[str] = None
    ciudad: Optional[str] = None


class Sugerencia(BaseModel):
    codigo: str
    descripcion: str
    uvr: Optional[int] = None


class ProcedimientoExtraido(_Base):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    es_principal: bool = False
    codigo_sugerido: bool = False          # el código lo puso la app desde el manual ISS, no venía en la orden
    sugerencias: list[Sugerencia] = []     # opciones del manual ISS para elegir el código


class OrdenExtraida(_Base):
    paciente: PacienteExtraido = PacienteExtraido()
    aseguradora: AseguradoraExtraida = AseguradoraExtraida()
    clinica: ClinicaExtraida = ClinicaExtraida()
    procedimientos: list[ProcedimientoExtraido] = []
    fecha_procedimiento: Optional[date] = None
    cirujano: Optional[str] = None
    confianza: float = Field(default=0, ge=0, le=1)
    campos_dudosos: list[str] = []
    observaciones: Optional[str] = None

    @field_validator("fecha_procedimiento", mode="before")
    @classmethod
    def _fecha_invalida_a_nulo(cls, v):
        # Si la IA devuelve una fecha imposible, se deja vacía para que el usuario la escriba
        if isinstance(v, str):
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
        return v

    @field_validator("confianza", mode="before")
    @classmethod
    def _acotar_confianza(cls, v):
        return min(max(float(v or 0), 0.0), 1.0)


# ---------------------------------------------------------------- confirmación
class PacienteConfirmado(_Base):
    tipo_documento: TipoDocumento = "CC"
    numero_documento: str = Field(min_length=3, max_length=20)
    nombres: str = Field(min_length=1, max_length=100)
    apellidos: str = Field(min_length=1, max_length=100)

    @field_validator("numero_documento")
    @classmethod
    def _solo_alfanumerico(cls, v: str) -> str:
        # "1.020.304.050" -> "1020304050"
        v = "".join(ch for ch in v if ch.isalnum()).upper()
        if len(v) < 3:
            raise ValueError("número de documento inválido")
        return v


class AseguradoraConfirmada(_Base):
    nombre: str = Field(min_length=2, max_length=150)
    tipo: TipoAseguradora
    numero_poliza: Optional[str] = Field(default=None, max_length=50)
    plan: Optional[str] = Field(default=None, max_length=100)


class ClinicaConfirmada(_Base):
    nombre: str = Field(min_length=2, max_length=150)
    ciudad: Optional[str] = Field(default=None, max_length=80)


class ProcedimientoConfirmado(_Base):
    codigo: str = Field(min_length=3, max_length=10)
    nombre: str = Field(min_length=2, max_length=255)
    es_principal: bool = False

    @field_validator("codigo")
    @classmethod
    def _normalizar_codigo(cls, v: str) -> str:
        v = v.replace(" ", "").replace(".", "").replace("-", "").upper()
        if not v.isalnum():
            raise ValueError(f"el código {v} solo puede tener letras y números")
        return v


class OrdenConfirmada(_Base):
    paciente: PacienteConfirmado
    aseguradora: Optional[AseguradoraConfirmada] = None  # None = particular
    clinica: ClinicaConfirmada
    procedimientos: list[ProcedimientoConfirmado] = Field(min_length=1)
    fecha_procedimiento: date
    cirujano: Optional[str] = Field(default=None, max_length=150)
    estado: EstadoCirugia = "PROGRAMADA"
    valor_honorarios: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    fecha_pago: Optional[date] = None
    observaciones: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("valor_honorarios", mode="before")
    @classmethod
    def _valor_en_pesos(cls, v):
        # Acepta "1.200.000", "$ 1,200,000" o 1200000: los pesos se manejan sin decimales
        if isinstance(v, str):
            digitos = "".join(ch for ch in v if ch.isdigit())
            return Decimal(digitos) if digitos else None
        return v

    @model_validator(mode="after")
    def _un_principal_y_sin_repetidos(self):
        codigos = [p.codigo for p in self.procedimientos]
        if len(codigos) != len(set(codigos)):
            raise ValueError("hay códigos de procedimiento repetidos")
        principales = [p for p in self.procedimientos if p.es_principal]
        if len(principales) > 1:
            raise ValueError("solo un procedimiento puede ser el principal")
        if not principales:
            self.procedimientos[0].es_principal = True
        return self


# ---------------------------------------------------------------- reportes de pago
def _fecha_o_nulo(v):
    if isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return v


def _pesos_o_nulo(v):
    if isinstance(v, str):
        digitos = "".join(ch for ch in v if ch.isdigit() or ch == "-")
        return Decimal(digitos) if digitos.strip("-") else None
    return v


class FilaPago(_Base):
    empresa: Optional[str] = None
    documento_paciente: Optional[str] = None
    paciente: Optional[str] = None
    fecha_servicio: Optional[date] = None
    factura: Optional[str] = None
    autorizacion: Optional[str] = None
    total: Optional[Decimal] = None
    glosas: Decimal = Decimal(0)
    descuentos: Decimal = Decimal(0)
    neto: Optional[Decimal] = None
    es_paciente: bool = True

    _f = field_validator("fecha_servicio", mode="before")(_fecha_o_nulo)
    _p = field_validator("total", "neto", mode="before")(_pesos_o_nulo)

    @field_validator("glosas", "descuentos", mode="before")
    @classmethod
    def _cero(cls, v):
        v = _pesos_o_nulo(v)
        return Decimal(0) if v is None else v

    @field_validator("documento_paciente")
    @classmethod
    def _doc(cls, v):
        return "".join(ch for ch in v if ch.isalnum()).upper() if v else v


class ReportePagoExtraido(_Base):
    pagador: Optional[str] = None
    prestador: Optional[str] = None
    fecha_proceso: Optional[date] = None
    periodo_desde: Optional[date] = None
    periodo_hasta: Optional[date] = None
    total_neto: Optional[Decimal] = None
    filas: list[FilaPago] = []

    _f = field_validator("fecha_proceso", "periodo_desde", "periodo_hasta", mode="before")(_fecha_o_nulo)
    _p = field_validator("total_neto", mode="before")(_pesos_o_nulo)

    @property
    def suma_neto(self) -> Decimal:
        return sum((f.neto or Decimal(0) for f in self.filas), Decimal(0))

    @property
    def cuadra(self) -> Optional[bool]:
        """¿La suma de las filas coincide con el total del reporte? (None si no hay total)."""
        if self.total_neto is None:
            return None
        return abs(self.suma_neto - self.total_neto) <= 1
