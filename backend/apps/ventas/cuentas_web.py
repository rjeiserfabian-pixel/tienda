"""Nombres de las cuentas que usa el cobro de la tienda virtual (Culqi) en cada empresa.

Viven aquí (y no en ``tienda``) para que ``ventas`` pueda liquidar esos cobros sin depender de la
tienda: la tienda importa estos nombres al crear las cuentas.

* ``CUENTA_COBRA``: donde cae el dinero de Culqi en la empresa que tiene la cuenta de Culqi.
* ``CUENTA_PUENTE``: en la OTRA empresa, donde se anota lo que le corresponde de un pago que
  recibió su socia. Es una cuenta de paso: la liquidación entre empresas la deja en cero.
"""

CUENTA_COBRA = "Culqi (tienda virtual)"
CUENTA_PUENTE = "Culqi (cobrado por otra empresa)"
# Las partidas de los cobros de la tienda se agrupan aparte de las de los locales físicos.
LOCAL_WEB = "TIENDA_WEB"
