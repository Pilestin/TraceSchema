#!/usr/bin/env python3
"""
Schema Documentation Generator
================================
schema/ klasöründeki XSD dosyalarını parse ederek otomatik HTML dokümantasyon üretir.
Çıktıyı docs/schema/_site/ altına yazar.
"""
import os
import sys
from lxml import etree
from jinja2 import Template

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(REPO_ROOT, "schema")
DOCS_DIR = os.path.join(REPO_ROOT, "docs", "schema")
OUTPUT_DIR = os.path.join(DOCS_DIR, "_site")

XSD_NS = "http://www.w3.org/2001/XMLSchema"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{{ title }}</title>
  <style>
    body { font-family: sans-serif; max-width: 960px; margin: 2em auto; padding: 0 1em; }
    h1 { border-bottom: 2px solid #333; }
    h2 { border-bottom: 1px solid #aaa; color: #444; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { border: 1px solid #ccc; padding: 0.4em 0.8em; text-align: left; }
    th { background: #f0f0f0; }
    code { background: #f8f8f8; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.95em; }
    pre { background: #f8f8f8; padding: 1em; border-radius: 4px; overflow-x: auto; }
    .version-badge { display:inline-block; background:#0366d6; color:#fff; 
                     border-radius:4px; padding:2px 8px; font-size:0.85em; }
    .diff-added { color: #22863a; background: #f0fff4; }
    .diff-removed { color: #cb2431; background: #ffeef0; }
    nav a { margin-right: 1em; }
  </style>
</head>
<body>
  <nav>
    {% for schema in schemas %}
    <a href="{{ schema.filename }}">{{ schema.version }}</a>
    {% endfor %}
    <a href="diff.html">Diff v1→v2</a>
  </nav>
  <h1>{{ title }} <span class="version-badge">{{ version }}</span></h1>
  <p>Schema file: <code>{{ schema_file }}</code></p>

  <h2>Complex Types</h2>
  {% for ctype in complex_types %}
  <h3><code>{{ ctype.name }}</code></h3>
  {% if ctype.doc %}
  <p>{{ ctype.doc }}</p>
  {% endif %}
  {% if ctype.elements %}
  <table>
    <tr><th>Element</th><th>Type</th><th>Required</th><th>Description</th></tr>
    {% for el in ctype.elements %}
    <tr>
      <td><code>{{ el.name }}</code></td>
      <td><code>{{ el.type }}</code></td>
      <td>{{ "yes" if el.required else "no" }}</td>
      <td>{{ el.doc }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}
  {% if ctype.attributes %}
  <h4>Attributes</h4>
  <table>
    <tr><th>Attribute</th><th>Type</th><th>Required</th><th>Description</th></tr>
    {% for attr in ctype.attributes %}
    <tr>
      <td><code>{{ attr.name }}</code></td>
      <td><code>{{ attr.type }}</code></td>
      <td>{{ "yes" if attr.required else "no" }}</td>
      <td>{{ attr.doc }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}
  {% endfor %}
</body>
</html>
"""

DIFF_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Schema Diff v1 → v2</title>
  <style>
    body { font-family: sans-serif; max-width: 960px; margin: 2em auto; padding: 0 1em; }
    h1 { border-bottom: 2px solid #333; }
    .added { color: #22863a; background: #f0fff4; padding: 2px 6px; border-radius:3px; }
    .removed { color: #cb2431; background: #ffeef0; padding: 2px 6px; border-radius:3px; }
    ul li { margin: 0.3em 0; }
  </style>
</head>
<body>
  <h1>Schema Diff: v1 → v2</h1>
  <h2>Added Types</h2>
  <ul>{% for t in added %}<li class="added">{{ t }}</li>{% endfor %}</ul>
  <h2>Removed Types</h2>
  <ul>{% for t in removed %}<li class="removed">{{ t }}</li>{% endfor %}</ul>
  <h2>Common Types</h2>
  <ul>{% for t in common %}<li>{{ t }}</li>{% endfor %}</ul>
</body>
</html>
"""


def parse_xsd(xsd_path: str) -> dict:
    """Parse an XSD file and extract type information."""
    with open(xsd_path, 'rb') as f:
        root = etree.parse(f).getroot()

    def get_doc(elem):
        ann = elem.find(f'{{{XSD_NS}}}annotation')
        if ann is not None:
            doc = ann.find(f'{{{XSD_NS}}}documentation')
            if doc is not None and doc.text:
                return doc.text.strip()
        return ''

    complex_types = []
    for ct in root.findall(f'{{{XSD_NS}}}complexType'):
        name = ct.get('name', '')
        doc = get_doc(ct)
        elements = []
        attributes = []

        for el in ct.iter(f'{{{XSD_NS}}}element'):
            if el.getparent() is not None:
                elements.append({
                    'name': el.get('name', ''),
                    'type': el.get('type', 'complex'),
                    'required': el.get('minOccurs', '1') != '0',
                    'doc': get_doc(el),
                })

        for attr in ct.iter(f'{{{XSD_NS}}}attribute'):
            attributes.append({
                'name': attr.get('name', ''),
                'type': attr.get('type', 'xs:string'),
                'required': attr.get('use', 'optional') == 'required',
                'doc': get_doc(attr),
            })

        complex_types.append({
            'name': name,
            'doc': doc,
            'elements': elements,
            'attributes': attributes,
        })

    version = root.get('version', '1.0')
    return {'version': version, 'complex_types': complex_types}


def generate_docs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    schema_files = {
        'v1': os.path.join(SCHEMA_DIR, 'trace_schema_v1.xsd'),
        'v2': os.path.join(SCHEMA_DIR, 'trace_schema.xsd'),
    }

    schemas_meta = []
    parsed = {}

    for ver, path in schema_files.items():
        if not os.path.exists(path):
            print(f"Warning: {path} not found, skipping")
            continue
        data = parse_xsd(path)
        parsed[ver] = data
        schemas_meta.append({
            'version': f"Schema {ver}",
            'filename': f"schema_{ver}.html",
        })

    tmpl = Template(HTML_TEMPLATE)
    for ver, data in parsed.items():
        html = tmpl.render(
            title=f"Trace Schema",
            version=f"v{data['version']}",
            schema_file=f"trace_schema{'_v1' if ver == 'v1' else ''}.xsd",
            complex_types=data['complex_types'],
            schemas=schemas_meta,
        )
        out_path = os.path.join(OUTPUT_DIR, f"schema_{ver}.html")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Generated: {out_path}")

    # Generate diff
    if 'v1' in parsed and 'v2' in parsed:
        v1_types = {ct['name'] for ct in parsed['v1']['complex_types']}
        v2_types = {ct['name'] for ct in parsed['v2']['complex_types']}
        diff_html = Template(DIFF_TEMPLATE).render(
            added=sorted(v2_types - v1_types),
            removed=sorted(v1_types - v2_types),
            common=sorted(v1_types & v2_types),
        )
        diff_path = os.path.join(OUTPUT_DIR, 'diff.html')
        with open(diff_path, 'w', encoding='utf-8') as f:
            f.write(diff_html)
        print(f"Generated: {diff_path}")

    schema_links = "".join(
        f'<li><a href="{s["filename"]}">{s["version"]}</a></li>'
        for s in schemas_meta
    )
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Trace Schema Docs</title></head>
<body>
<h1>Trace Schema Documentation</h1>
<ul>
  {schema_links}
  <li><a href="diff.html">Schema Diff v1 -&gt; v2</a></li>
</ul>
</body>
</html>"""
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html)
    print(f"Generated: {os.path.join(OUTPUT_DIR, 'index.html')}")


if __name__ == '__main__':
    generate_docs()
