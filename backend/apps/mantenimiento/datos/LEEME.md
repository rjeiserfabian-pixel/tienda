# Ubigeos del INEI

`ubigeos_inei.csv` es la lista de ubigeos (código de 6 dígitos: departamento + provincia + distrito)
con los códigos del **INEI**, que son los que usa SUNAT en la guía de remisión electrónica. La carga
la migración `0034_cargar_ubigeos`.

- **25** departamentos, **196** provincias y **1 893** distritos.
- Origen: el repositorio público `yull23/ubigeos_peru` (carpeta `resources_readable`, columna
  «inei»), descargado el 2026-11-03. Ese repositorio dice basarse en datos públicos del INEI.
- Se verificó que cada distrito tiene su provincia y departamento, que no hay códigos repetidos y
  que los nombres son legibles. Se descartó una entrada del origen con un código de provincia
  ilegible (la de Callao, que ya existe con su código `0701`).

**Antes de usarlo en producción**, contrastarlo con la publicación oficial vigente del INEI: se crean
distritos nuevos de vez en cuando. Para actualizarlo se reemplaza el CSV y se agrega una migración
que cargue lo que falta (la migración actual no borra ni modifica lo ya cargado).
