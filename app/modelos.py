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


class ProcedimientoExtraido(_Base):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    es_principal: bool = False
    codigo_sugerido: bool = False          # el código lo puso la app desde el catálogo CUPS, no venía en la orden
    sugerencias: list[Sugerencia] = []     # opciones del catálogo CUPS para elegir el código


class OrdenExtraida(_Base):
    paciente: PacienteExtraido = PacienteExtraido()
    aseguradora: AseguradoraExtraida = AseguradoraExtraida()
    clinica: ClinicaExtraida = ClinicaExtraida()
    procedimientos: list[ProcedimientoExtraido] = []
    fecha_procedimiento: Optional[date] = None
    cirujano: Optional[str] = None
    numero_orden: Optional[str] = None
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
    numero_orden: Optional[str] = Field(default=None, max_length=100)
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


# ---------------------------------------------------------------- volante de AP
class OtroConcepto(_Base):
    concepto: Optional[str] = None
    devengado: Optional[Decimal] = None
    deducido: Optional[Decimal] = None

    _p = field_validator("devengado", "deducido", mode="before")(_pesos_o_nulo)


class VolanteExtraido(_Base):
    """Valores del volante de liquidación que entrega la asociación (para compararlo con el calculado)."""
    fecha_proceso: Optional[date] = None
    periodo_desde: Optional[date] = None
    periodo_hasta: Optional[date] = None
    probienestar: Optional[Decimal] = None
    compensacion_ordinaria: Optional[Decimal] = None
    compensacion_extraordinaria: Optional[Decimal] = None
    auxilio_sindical: Optional[Decimal] = None
    cuatro_por_mil: Optional[Decimal] = None
    cuota_sostenimiento: Optional[Decimal] = None
    salud: Optional[Decimal] = None
    pension: Optional[Decimal] = None
    ajuste_sindical: Optional[Decimal] = None
    neto: Optional[Decimal] = None
    otros: list[OtroConcepto] = []
    # "ACUMULADO DE APORTES" del pie del volante
    acumulado_aporte_sindical: Optional[Decimal] = None
    acumulado_semestral: Optional[Decimal] = None
    acumulado_anual: Optional[Decimal] = None
    acumulado_vacaciones: Optional[Decimal] = None

    _f = field_validator("fecha_proceso", "periodo_desde", "periodo_hasta", mode="before")(_fecha_o_nulo)
    _p = field_validator("probienestar", "compensacion_ordinaria", "compensacion_extraordinaria", "auxilio_sindical",
                         "cuatro_por_mil", "cuota_sostenimiento", "salud", "pension", "ajuste_sindical",
                         "neto", "acumulado_aporte_sindical", "acumulado_semestral", "acumulado_anual",
                         "acumulado_vacaciones", mode="before")(_pesos_o_nulo)


# ---------------------------------------------------------------- finanzas personales
def _pesos_positivos(v):
    if isinstance(v, str):
        digitos = "".join(ch for ch in v if ch.isdigit())
        return Decimal(digitos) if digitos else None
    return v


class PartidaEntrada(_Base):
    clase: Literal["GASTO", "INGRESO"]
    categoria: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=1, max_length=120)
    valor_mensual: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    saldo: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)   # solo créditos
    tasa_ea: Optional[Decimal] = Field(default=None, ge=0, le=200, max_digits=6, decimal_places=2)  # % efectivo anual

    _p = field_validator("valor_mensual", "saldo", mode="before")(_pesos_positivos)

    @field_validator("tasa_ea", mode="before")
    @classmethod
    def _tasa(cls, v):  # acepta "24,5" o "24.5"
        if isinstance(v, str):
            v = v.replace("%", "").replace(",", ".").strip()
            return Decimal(v) if v else None
        return v

    @model_validator(mode="after")
    def _categoria_valida(self):
        from app.finanzas import CATEGORIAS, CATEGORIAS_INGRESO
        validas = [c[0] for c in (CATEGORIAS if self.clase == "GASTO" else CATEGORIAS_INGRESO)]
        if self.categoria not in validas:
            raise ValueError(f"categoría inválida: {self.categoria}")
        return self


class MetaEntrada(_Base):
    tipo: Literal["EMERGENCIA", "VIAJE", "CARRO", "CASA", "EDUCACION", "RETIRO", "OTRO"]
    nombre: str = Field(min_length=1, max_length=120)
    valor_objetivo: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    ahorrado: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    fecha_objetivo: Optional[date] = None

    _p = field_validator("valor_objetivo", "ahorrado", mode="before")(_pesos_positivos)

    @field_validator("ahorrado", mode="before")
    @classmethod
    def _cero(cls, v):
        return Decimal(0) if v in (None, "") else v


class MovimientoEntrada(_Base):
    """Un gasto real del mes o un aporte a una meta."""
    clase: Literal["GASTO", "APORTE"]
    fecha: date = Field(default_factory=date.today)
    categoria: Optional[str] = None
    meta_id: Optional[int] = None
    descripcion: Optional[str] = Field(default=None, max_length=160)
    valor: Decimal = Field(gt=0, max_digits=14, decimal_places=2)

    _p = field_validator("valor", mode="before")(_pesos_positivos)

    @model_validator(mode="after")
    def _segun_clase(self):
        from app.finanzas import CATEGORIAS
        if self.clase == "GASTO" and self.categoria not in [c[0] for c in CATEGORIAS]:
            raise ValueError("elige la categoría del gasto")
        if self.clase == "APORTE" and not self.meta_id:
            raise ValueError("elige la meta del aporte")
        return self


class CompromisoEntrada(_Base):
    compromiso_mensual: Optional[Decimal] = Field(default=None, gt=0, max_digits=14, decimal_places=2)

    _p = field_validator("compromiso_mensual", mode="before")(_pesos_positivos)
