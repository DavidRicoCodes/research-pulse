# Research Pulse — David Rico

Dashboard estático para seguir la evolución de publicaciones, citas e índice h de David Rico. Consolida perfiles fragmentados de OpenAlex y Semantic Scholar y conserva una observación manual de Google Scholar, que no ofrece una API pública estable.

## Ejecutarlo

Solo requiere Python 3.11 o posterior:

```powershell
python collector.py
python -m http.server 8000
```

Después abre <http://localhost:8000>. No abras `index.html` directamente: los navegadores bloquean la lectura del JSON local mediante `fetch`.

## Fuentes

- Google Scholar: perfil `ZIIlvkAAAAAJ`. El colector intenta leer una vez al día el perfil público; `data/manual-sources.json` conserva el último snapshot manual como fallback si Google bloquea temporalmente la consulta.
- OpenAlex: perfiles `A5099980835` y `A5114996487`.
- Semantic Scholar: perfiles `2342699301` y `2425315603`.

El colector fusiona artículos por DOI y, cuando falta, por un título normalizado. Para perfiles duplicados del mismo proveedor conserva el mayor recuento de citas del artículo; nunca suma ambos perfiles. El dashboard agrupa el histórico de Scholar por fecha real de observación, de modo que un fallback antiguo no simula días de medición inexistentes.

## Automatización

`.github/workflows/collect.yml` ejecuta el colector diariamente a las 04:17 UTC y guarda el snapshot en Git. Al publicar el repositorio con GitHub Pages, la raíz del repositorio es el dashboard y no necesita servidor ni base de datos.

Google Scholar bloquea habitualmente las direcciones IP de los runners de GitHub. En este equipo, la tarea programada `Research Pulse - Google Scholar` ejecuta `scripts/refresh-local.ps1` a las 20:00. El script hace una sola consulta al perfil público, exige que el dato tenga fecha de hoy y publica únicamente `data/history.json`; si hay cambios locales, un bloqueo de Google o un error de red, se detiene sin sobrescribir nada. El registro local se guarda en `.logs/scholar-refresh.log` y no se publica.

## Próximos pasos

1. Confirmar qué artículos pertenecen realmente a David cuando una fuente encuentre candidatos nuevos.
2. Añadir diferencias diarias y actividad por paper tras acumular varios snapshots.
3. Decidir si Google Scholar se actualiza manualmente o mediante una integración opcional y tolerante a fallos.
