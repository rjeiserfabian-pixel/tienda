from apps.core.exceptions import ErrorDominio


class CredencialesInvalidas(ErrorDominio):
    """Mensaje único para usuario inexistente, clave errónea o cuenta inactiva."""

    status_code = 401
    codigo = "credenciales_invalidas"
    mensaje = "Usuario o contraseña incorrectos."


class CuentaBloqueadaTemporalmente(ErrorDominio):
    status_code = 429
    codigo = "login_bloqueado"
    mensaje = "Demasiados intentos fallidos. Intente nuevamente más tarde."

    def __init__(self, segundos: int):
        super().__init__(cabeceras={"Retry-After": str(max(segundos, 1))})


class OrganizacionInactiva(ErrorDominio):
    status_code = 403
    codigo = "organizacion_inactiva"
    mensaje = "La organización no está activa. Contacte al administrador."


class SinAccesoEmpresas(ErrorDominio):
    status_code = 403
    codigo = "sin_acceso_empresas"
    mensaje = "No tiene acceso vigente a ninguna empresa. Contacte al administrador."


class SesionInvalida(ErrorDominio):
    status_code = 401
    codigo = "sesion_invalida"
    mensaje = "La sesión no es válida. Inicie sesión nuevamente."


class RefreshConcurrente(ErrorDominio):
    """Dos refrescos casi simultáneos con el mismo token (p. ej. dos pestañas)."""

    status_code = 409
    codigo = "refresh_concurrente"
    mensaje = "La sesión se está renovando. Reintente en un momento."


class PasswordActualIncorrecta(ErrorDominio):
    status_code = 400
    codigo = "password_actual_incorrecta"
    mensaje = "La contraseña actual no es correcta."


class PasswordReutilizada(ErrorDominio):
    status_code = 400
    codigo = "password_reutilizada"
    mensaje = "No puede reutilizar una de sus últimas contraseñas."


class PermisoDenegado(ErrorDominio):
    status_code = 403
    codigo = "permiso_denegado"
    mensaje = "No tiene permiso para realizar esta operación."


class EscaladaDePrivilegios(ErrorDominio):
    """Se intentó otorgar algo que el solicitante no posee (o con mayor alcance)."""

    status_code = 403
    codigo = "escalada_de_privilegios"
    mensaje = "No puede otorgar permisos que usted no posee."


class RolDeSistemaIntocable(ErrorDominio):
    status_code = 409
    codigo = "rol_de_sistema_intocable"
    mensaje = "Los roles de sistema no se pueden modificar ni eliminar."


class UltimoAdministrador(ErrorDominio):
    status_code = 409
    codigo = "ultimo_administrador"
    mensaje = "La organización no puede quedarse sin un administrador."


class RolEnUso(ErrorDominio):
    status_code = 409
    codigo = "rol_en_uso"
    mensaje = "El rol tiene usuarios asignados. Quite las asignaciones primero."


class SeparacionDeFunciones(ErrorDominio):
    status_code = 403
    codigo = "separacion_de_funciones"
    mensaje = "La misma persona no puede realizar ambos pasos de esta operación."


class MotivoRequerido(ErrorDominio):
    status_code = 400
    codigo = "motivo_requerido"
    mensaje = "Debe indicar el motivo."


class UsuarioConMasPrivilegios(ErrorDominio):
    """Quien actúa no puede afectar a alguien con permisos que él mismo no posee."""

    status_code = 403
    codigo = "usuario_con_mas_privilegios"
    mensaje = "No puede modificar a un usuario con más privilegios que usted."


class OperacionSobreSiMismo(ErrorDominio):
    status_code = 409
    codigo = "operacion_sobre_si_mismo"
    mensaje = "No puede realizar esta operación sobre su propia cuenta."


class CambioPasswordRequerido(ErrorDominio):
    """La contraseña es temporal: hasta cambiarla solo se permite cambiarla."""

    status_code = 403
    codigo = "cambio_password_requerido"
    mensaje = "Debe cambiar su contraseña temporal antes de continuar."


class MfaConfiguracionRequerida(ErrorDominio):
    """La organización exige segundo factor y el usuario aún no lo activó."""

    status_code = 403
    codigo = "mfa_configuracion_requerida"
    mensaje = "Su organización exige verificación en dos pasos. Actívela para continuar."


class MfaCodigoInvalido(ErrorDominio):
    status_code = 400
    codigo = "mfa_codigo_invalido"
    mensaje = "El código de verificación no es correcto."


class DesafioMfaInvalido(ErrorDominio):
    status_code = 401
    codigo = "desafio_mfa_invalido"
    mensaje = "La verificación expiró. Inicie sesión nuevamente."


class MfaYaActivo(ErrorDominio):
    status_code = 409
    codigo = "mfa_ya_activo"
    mensaje = "La verificación en dos pasos ya está activa."


class MfaNoActivo(ErrorDominio):
    status_code = 409
    codigo = "mfa_no_activo"
    mensaje = "La verificación en dos pasos no está activa."


class MfaObligatoria(ErrorDominio):
    status_code = 409
    codigo = "mfa_obligatoria"
    mensaje = "Su organización exige la verificación en dos pasos: no se puede desactivar."


class TokenRecuperacionInvalido(ErrorDominio):
    """Mensaje único para token inexistente, vencido o ya usado."""

    status_code = 400
    codigo = "token_recuperacion_invalido"
    mensaje = "El enlace de recuperación no es válido o ya venció."
