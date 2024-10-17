import os
import json
from lxml import etree

from pagexml.parser import parse_pagexml_file

import iiif_prezi3

from SPARQLWrapper import SPARQLWrapper, JSON

iiif_prezi3.config.configs["helpers.auto_fields.AutoLang"].auto_lang = "nl"

IIIF_SERVER = "https://iiif.create.humanities.uva.nl/iiif/"

PREFIX = "https://amsterdamtimemachine.github.io/datasprint-annoteren-2024/manifests/diaries/"
PREFIX_LOCAL = "manifests/diaries/"

line2coords = dict()


def make_manifest(diary_id, filenames):

    manifest_id = f"{PREFIX}/{diary_id}/manifest.json"
    manifest = iiif_prezi3.Manifest(id=manifest_id, label="")

    for file_info_json in filenames:

        basefilename = os.path.splitext(
            os.path.basename(file_info_json.replace("/info.json", ""))
        )[0]

        canvas_uri = f"{PREFIX}{diary_id}/{basefilename}"

        manifest.make_canvas_from_iiif(
            url=file_info_json,
            id=canvas_uri,
            anno_page_id=f"{canvas_uri}/p0/page",
            anno_id=f"{canvas_uri}/p0/page/anno",
            label=basefilename,
            # metadata=[
            #     iiif_prezi3.KeyValueString(
            #         label="Titel",
            #         value={"nl": [label]},
            #     ),
            #     iiif_prezi3.KeyValueString(
            #         label="URI (Beeldbank)",
            #         value={"nl": [f'<a href="{uri_handle}">{uri_handle}</a>']},
            #     ),
            #     iiif_prezi3.KeyValueString(
            #         label="URI (Catalogus)",
            #         value={"en": [f'<a href="{uri_ark}">{uri_ark}</a>']},
            #     ),
            # ],
        )

    return manifest


def getSVG(coordinates):

    points = [f"{int(x)},{int(y)}" for x, y in coordinates + [coordinates[0]]]

    svg = etree.Element("svg", xmlns="http://www.w3.org/2000/svg")
    _ = etree.SubElement(
        svg,
        "polygon",
        points=" ".join(points),
    )

    return etree.tostring(svg, encoding=str)


def query_wikidata(uri, endpoint="https://query.wikidata.org/sparql", cache=dict()):

    if uri in cache:
        return cache[uri]

    q = """
    SELECT DISTINCT ?uri ?uriLabel ?uriDescription ?latitude ?longitude WHERE {
        ?uri wdt:P31|wdt:P279 [] .
        
        VALUES ?uri { <URIHIER> }

        SERVICE wikibase:label { bd:serviceParam wikibase:language "nl,en,de". }
    }
    """.replace(
        "URIHIER", uri
    )

    print(uri)

    sparql = SPARQLWrapper(
        endpoint, agent="example-UA (https://example.com/; mail@example.com)"
    )
    sparql.setQuery(q)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    label = results["results"]["bindings"][0]["uriLabel"]["value"]
    description = (
        results["results"]["bindings"][0].get("uriDescription", {}).get("value")
    )

    cache[uri] = label, description
    return label, description


def get_custom_tags(doc) -> list[dict[str, any]]:
    """
    Get all custom tags and their textual values from a PageXMLDoc.

    This function assumes that the PageXML document is generated with
    input of some `custom_tags` in the parse_pagexml_file function.
    This helper retrieves those tags from all TextLines and finds the
    corresponding text from their offset and length. It returns a
    dictionary with the tag type, the textual value, region and line
    id, and the offset and length.

    :param doc: A PageXMLDoc
    :type doc: pdm.PageXMLDoc
    :return: List of custom tags
    :rtype: List[Dict[str, any]]
    """
    custom_tags = []

    for region in doc.text_regions:
        for line in region.lines:
            for tag_el in line.metadata.get("custom_tags", []):
                tag = tag_el["type"]
                offset = tag_el["offset"]
                length = tag_el["length"]

                value = line.text[offset : offset + length]

                custom_tags.append(
                    {
                        "type": tag,
                        "value": value,
                        "region_id": region.id,
                        "line_id": line.id,
                        "offset": offset,
                        "length": length,
                        "wikidata": tag_el.get("wikiData", None),  # <-- this is new
                        "date": tag_el.get("yyyy-mm-dd", None),  # TODO?
                    }
                )

    return custom_tags


def parse_layout(page, canvas_uri):

    annotation_page_id = f"{canvas_uri}_layout.json"

    annotationPage = {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": f"{canvas_uri}_layout.json",
        "type": "AnnotationPage",
        "items": [],
    }

    for region in page.text_regions:

        region_type = region.types.difference(
            {"physical_structure_doc", "pagexml_doc", "text_region"}
        )

        region_annotation = {
            "@context": [
                "http://www.w3.org/ns/anno.jsonld",
                "http://iiif.io/api/extension/text-granularity/context.json",
            ],
            "id": f"{annotation_page_id}/{region.id}",
            "type": "Annotation",
            "textGranularity": "block",
            "motivation": "tagging",
            "body": [
                {
                    "type": "TextualBody",
                    "value": list(region_type)[0] if region_type else "unknown",
                },
            ],
            "target": {
                "type": "SpecificResource",
                "source": canvas_uri,
                "selector": [
                    {
                        "type": "SvgSelector",
                        "value": getSVG(region.coords.points),
                        "conformsTo": "http://www.w3.org/TR/SVG/",
                    },
                ],
            },
        }

        annotationPage["items"].append(region_annotation)

    with open(annotation_page_id.replace(PREFIX, PREFIX_LOCAL), "w") as f:
        f.write(json.dumps(annotationPage, indent=2))

    return iiif_prezi3.Reference(
        id=annotation_page_id,
        label="Layout annotations",
        type="AnnotationPage",
    )


def parse_transcriptions(page, canvas_uri):

    annotation_page_id = f"{canvas_uri}_transcriptions.json"

    annotationPage = {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": annotation_page_id,
        "type": "AnnotationPage",
        "items": [],
    }

    for region in page.text_regions:

        for line in region.lines:

            line_annotation = {
                "@context": [
                    "http://www.w3.org/ns/anno.jsonld",
                    "http://iiif.io/api/extension/text-granularity/context.json",
                ],
                "id": f"{annotation_page_id}/{line.id}",
                "type": "Annotation",
                "textGranularity": "line",
                "motivation": "supplementing",
                "body": [
                    {
                        # "id": body_id,
                        "type": "TextualBody",
                        "value": line.text if line.text else "",
                    },
                ],
                "target": f"{canvas_uri}#xywh={max(0, line.coords.x)},{max(0, line.coords.y)},{min(page.coords.w - line.coords.x, line.coords.w)},{min(page.coords.h - line.coords.y, line.coords.h)}",
            }
            annotationPage["items"].append(line_annotation)

            line2coords[f"{canvas_uri}_{line.id}"] = line_annotation["target"]

    with open(annotation_page_id.replace(PREFIX, PREFIX_LOCAL), "w") as f:
        f.write(json.dumps(annotationPage, indent=2))

    return iiif_prezi3.Reference(
        id=annotation_page_id,
        label="Transcriptions",
        type="AnnotationPage",
    )


def parse_entities(page, canvas_uri):

    annotation_page_id = f"{canvas_uri}_entities.json"

    annotationPage = {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": f"{canvas_uri}_entities.json",
        "type": "AnnotationPage",
        "items": [],
    }

    tags = get_custom_tags(page)

    for tag in tags:
        annotation = {
            "@context": [
                "http://www.w3.org/ns/anno.jsonld",
            ],
            # "id": line_id,
            "type": "Annotation",
            "body": [
                {
                    # "id": body_id,
                    "type": "TextualBody",
                    # "value": f"{tag['type'].title()}: {tag['value']}",
                    "value": f"<b>{tag['type'].title()}</b>: {tag['value']}",
                    "purpose": "classifying",
                    "format": "text/html",
                },
            ],
            "target": line2coords.get(f"{canvas_uri}_{tag['line_id']}"),
        }

        if tag["wikidata"]:

            wikidata_uri = f"http://www.wikidata.org/entity/{tag['wikidata']}"

            # get label and description from wikidata
            try:
                wikidata_label, wikidata_description = query_wikidata(wikidata_uri)
            except:
                wikidata_label, wikidata_description = "Unknown", "Unknown"

            annotation["body"].append(
                {
                    "type": "SpecificResource",
                    "source": {
                        "id": wikidata_uri,
                        "label": wikidata_label,
                        "comments": wikidata_description,
                    },
                    "purpose": "identifying",
                }
            )

            # Trick for the viewer
            annotation["body"][0][
                "value"
            ] += f"<br><br><b>Name</b>: {wikidata_label}<br><b>Description</b>: {wikidata_description}<br><b>URI</b>: <a href='{wikidata_uri}'>{wikidata_uri}</a>"

        annotationPage["items"].append(annotation)

    with open(annotation_page_id.replace(PREFIX, PREFIX_LOCAL), "w") as f:
        f.write(json.dumps(annotationPage, indent=2))

    return iiif_prezi3.Reference(
        id=annotation_page_id,
        label="Entity annotations",
        type="AnnotationPage",
    )


def main(DIARIESFILE):

    with open(DIARIESFILE, "r") as f:
        diaries = json.load(f)

    for diary in diaries:

        diary_id = diary["id"]
        os.makedirs(f"manifests/diaries/{diary_id}", exist_ok=True)
        manifest = make_manifest(diary_id, diary["images"])

        for xml_file in os.listdir(f"data/diaries/{diary_id}"):
            xml_file_path = os.path.join(f"data/diaries/{diary_id}", xml_file)

            page = parse_pagexml_file(
                xml_file_path,
                custom_tags=(
                    # "structure",
                    "date",
                    "person",
                    "place",
                    "organization",
                    "atm_food",
                    "atm_home",
                ),
            )

            filename_without_extension = os.path.splitext(os.path.basename(page.id))[0]
            canvas_uri = f"{PREFIX}{diary_id}/{filename_without_extension}"

            annotationPage_layout = parse_layout(page, canvas_uri)
            annotationPage_transcriptions = parse_transcriptions(page, canvas_uri)

            annotationPage_entities = parse_entities(page, canvas_uri)

            for c in manifest.items:

                if c.id == canvas_uri:

                    if not c.annotations:
                        c.annotations = []

                    c.annotations.append(annotationPage_transcriptions)
                    c.annotations.append(annotationPage_layout)
                    c.annotations.append(annotationPage_entities)

                    break

    with open(f"manifests/diaries/{diary_id}/manifest.json", "w") as outfile:
        outfile.write(manifest.json(indent=2))


if __name__ == "__main__":

    DIARIESFILE = "data/diaries.json"

    main(DIARIESFILE)
