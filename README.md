# Complementos de IngeCAD · IngeCAD plugins · Complementos do IngeCAD

**[Español](#español) · [English](#english) · [Português](#português)**

El catálogo que se ve en **https://ingecad.org/complementos**.
The catalog shown at **https://ingecad.org/complementos**.

---

## Español

Esto es un **directorio**, no una tienda. El código de cada complemento vive
en el repositorio de su autor. Aquí solo hay una **ficha** por complemento
(`extensions/<id>.toml`): nombre, descripción, licencia, enlace y la huella
(SHA-256) del archivo exacto que se instala.

IngeCAD ya trae dos complementos incluidos, **Topografía** y **Terreno**. Los
que se publican aquí son de la comunidad. El centro de extensiones dentro de
la aplicación, que lee este catálogo, llega con **IngeCAD 0.7**.

### Qué es un complemento de IngeCAD

Una **carpeta** cuyo `__init__.py` define `PLUGIN = PluginSpec(...)`: sus
comandos, herramientas, alias, su menú y, si quiere, una barra y una página
de opciones. El nombre de la carpeta es el `id` del complemento. Cómo se
escribe uno: la
[guía de complementos](https://github.com/ingelibre/ingecad/blob/main/docs/plugins.md)
y los dos complementos incluidos
([`plugins/`](https://github.com/ingelibre/ingecad/tree/main/plugins)).

Lo que se publica es un **`.zip` con esa carpeta y nada más**:

```
mi_complemento.zip
└── mi_complemento/
    ├── __init__.py      ← PLUGIN = PluginSpec(id="mi_complemento", ...)
    ├── tools.py
    └── i18n/es/ui.json
```

Sin archivos compilados (`.pyc`, `.so`, `.dll`): solo código que se pueda leer.

### Publicar tu complemento

No hace falta saber Git. Desde el navegador:

1. Publica tu complemento en tu propio repositorio (GitHub, Codeberg,
   GitLab…) con una licencia libre. Crea una **versión** (*release*) con una
   etiqueta (por ejemplo `v1.0`) y adjunta el `.zip`.
2. Aquí, abre [`TEMPLATE.toml`](TEMPLATE.toml), copia su contenido y pulsa
   **Add file ▸ Create new file** dentro de la carpeta `extensions/`. Ponle
   de nombre `<id>.toml` (por ejemplo `cuadro_de_areas.toml`) y pega la
   plantilla.
3. Rellena los campos. Para `sha256`:
   `sha256sum mi_complemento.zip` (Linux/Mac) o
   `certutil -hashfile mi_complemento.zip SHA256` (Windows). Si te
   equivocas, la revisión automática te dirá el valor correcto.
4. Opcional: sube una captura a `screenshots/` (png, jpg o webp, menos de
   600 KB, unos 1200×750).
5. Pulsa **Propose changes** y luego **Create pull request**.

Un robot revisa la ficha en un minuto: campos completos, licencia libre,
huella correcta, que el `.zip` sea seguro (una sola carpeta llamada como el
`id`, nada que salga de ella, sin enlaces ni archivos gigantes) y que su
`__init__.py` tenga un `PluginSpec`. **Lee el código, nunca lo ejecuta.** Si
algo falla, el mensaje explica qué corregir. Después la aprueba una persona
que mantiene IngeCAD y la página se actualiza sola en unos minutos.

**Nueva versión:** otra *pull request* cambiando `version`, `download` y
`sha256`. Si la envía la misma cuenta de GitHub que figura en `author_url`,
toca solo tu ficha (y su captura) y la revisión automática no encuentra nada
que leer, **se publica sola**, sin esperar a nadie. Sale como «Comunidad»
hasta que alguien lea el archivo nuevo.

### «Revisado» y «Comunidad»

Un complemento es código Python con el mismo acceso a tu computadora que
IngeCAD.

- **Revisado**: alguien que mantiene IngeCAD leyó **ese archivo exacto** (su
  huella está en `reviewed.toml`). Si sale una versión nueva, vuelve a
  «Comunidad» hasta que alguien la lea.
- **Comunidad**: pasó la revisión automática y se aprobó su ficha, pero
  nadie leyó el código a fondo. Instálalo si confías en su autor.

### Contacto

Por los *issues* de GitHub: un error en un complemento, en el repositorio de
ese complemento (enlace en su ficha); un problema con el catálogo,
[aquí](https://github.com/ingelibre/ingecad-extensions/issues); un error de
IngeCAD, en [ingelibre/ingecad](https://github.com/ingelibre/ingecad/issues).

### Para quienes mantienen el catálogo

- **Aprobar una ficha:** abre la *pull request*, mira el informe del robot
  (pestaña *Checks*: lista lo que usa la red, ejecuta programas o borra
  archivos) y pulsa **Merge**. Listo.
- **Marcarlo como revisado:** después de leer el código, añade a
  `reviewed.toml` su `sha256` (un commit directo en la web).
- **Quitar un complemento:** borra su ficha.
- **Probar en local:** `python -m pytest tests` y
  `python tools/catalog.py check` (Python 3.11 o más nuevo; solo la
  biblioteca estándar y pytest).

---

## English

This is a **directory**, not a store. Each plugin's code lives in its
author's repository; here there is one **entry** per plugin
(`extensions/<id>.toml`): name, description, licence, link and the
fingerprint (SHA-256) of the exact file that gets installed. IngeCAD ships
two plugins of its own, **Topography** and **Terrain**; the ones listed here
come from the community. The in-app extension center that reads this
catalog arrives with **IngeCAD 0.7**.

### What an IngeCAD plugin is

A **folder** whose `__init__.py` defines `PLUGIN = PluginSpec(...)`; the
folder's name is the plugin's `id`. See the
[plugin guide](https://github.com/ingelibre/ingecad/blob/main/docs/plugins.md).
What gets listed is a **`.zip` holding that one folder and nothing else**,
source only (no `.pyc`, `.so`, `.dll`).

### Listing your plugin

No Git needed. From the browser:

1. Publish your plugin in your own repository under a free licence, make a
   **release** with a tag (e.g. `v1.0`) and attach the `.zip`.
2. Here, copy [`TEMPLATE.toml`](TEMPLATE.toml), then **Add file ▸ Create new
   file** in `extensions/`, named `<id>.toml`, and paste it.
3. Fill it in. For `sha256`: `sha256sum my_plugin.zip` (Linux/Mac) or
   `certutil -hashfile my_plugin.zip SHA256` (Windows). If it is wrong, the
   check tells you the right value.
4. Optional: a screenshot in `screenshots/` (png, jpg or webp, under 600 KB).
5. **Propose changes** ▸ **Create pull request**.

A bot checks the entry within a minute: complete fields, free licence,
matching fingerprint, a safe zip (one folder named like the `id`, nothing
escaping it, no links, no huge files) and a `PluginSpec` in its
`__init__.py`. **It reads the code and never runs it.** Then a maintainer
approves it and the page updates by itself within minutes. A new version is
a new pull request changing `version`, `download` and `sha256`; when it
comes from the GitHub account in `author_url`, touches only your entry (and
its screenshot) and the check finds nothing to read, **it is published by
itself** — as «Community» until a maintainer reads the new file.

**Reviewed** means a maintainer read that exact file (its hash is in
`reviewed.toml`); a new version goes back to **Community** until read
again. **Community** entries passed the automatic check, but nobody read the
code in depth. A plugin is Python code with the same access to your
computer as IngeCAD itself.

Contact is through GitHub issues: the plugin's own repository for its bugs,
[this repository](https://github.com/ingelibre/ingecad-extensions/issues)
for the catalog, [ingelibre/ingecad](https://github.com/ingelibre/ingecad/issues)
for IngeCAD.

---

## Português

Um **diretório**, não uma loja: o código fica no repositório do autor. Um
complemento do IngeCAD é uma **pasta** cujo `__init__.py` define
`PLUGIN = PluginSpec(...)`
([guia](https://github.com/ingelibre/ingecad/blob/main/docs/plugins.md));
publica-se um **`.zip` com essa pasta e nada mais**, anexado a uma versão
(*release*) com etiqueta. Para publicar, copie [`TEMPLATE.toml`](TEMPLATE.toml)
para `extensions/<id>.toml` pelo navegador (**Add file ▸ Create new file**),
preencha e abra um *pull request*. Um robô verifica a ficha (sem executar o
código) e um mantenedor a aprova. **Revisado** = um mantenedor leu esse
arquivo exato; **Comunidade** = passou na verificação automática. Uma
**nova versão** enviada pela conta do GitHub que está em `author_url`, que
só altera a sua ficha e passa limpa na verificação, **é publicada sozinha**,
como «Comunidade». A central de extensões dentro do aplicativo chega com o
**IngeCAD 0.7**. Contato: pelas *issues* do GitHub.

---

The entries and `catalog.json` are dedicated to the public domain (CC0-1.0);
`tools/` and `tests/` are GPL-3.0-or-later. Each plugin keeps its own
licence.
