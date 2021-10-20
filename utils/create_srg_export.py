#! /usr/bin/env python3
import _io
import argparse
import csv
import datetime
import json
import pathlib
import os
import sys
import xml.etree.ElementTree as ET

import ssg.build_yaml
import ssg.constants
import ssg.controls
import ssg.environment
import ssg.rules
import ssg.yaml

SSG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RULES_JSON = os.path.join(SSG_ROOT, "build", "rule_dirs.json")
BUILD_CONFIG = os.path.join(SSG_ROOT, "build", "build_config.yml")
OUTPUT = os.path.join(SSG_ROOT, 'build', f'{datetime.datetime.now().strftime("%s")}.csv')
SRG_PATH = os.path.join(SSG_ROOT, 'shared', 'references', 'disa-os-srg-v2r1.xml')
NS = {'scap': ssg.constants.datastream_namespace,
      'xccdf-1.2': ssg.constants.XCCDF12_NS,
      'xccdf-1.1': ssg.constants.XCCDF11_NS}
SEVERITY = {'low': 'CAT III', 'medium': 'CAT II', 'high': 'CAT I'}


def get_description_root(srg: ET.Element) -> ET.Element:
    description_xml = "<root>"
    description_xml += srg.find('xccdf-1.1:description', NS).text.replace('&lt;', '<') \
        .replace('&gt;', '>').replace(' & ', '')
    description_xml += "</root>"
    description_root = ET.ElementTree(ET.fromstring(description_xml)).getroot()
    return description_root


def get_srg_dict(xml_path: str) -> dict:
    if not pathlib.Path(xml_path).exists():
        sys.stderr.write("XML for SRG was not found\n")
        exit(1)
    root = ET.parse(xml_path).getroot()
    srgs = dict()
    for group in root.findall('xccdf-1.1:Group', NS):
        for srg in group.findall('xccdf-1.1:Rule', NS):
            srg_id = srg.find('xccdf-1.1:version', NS).text
            srgs[srg_id] = dict()
            srgs[srg_id]['severity'] = SEVERITY[srg.get('severity')]
            srgs[srg_id]['title'] = srg.find('xccdf-1.1:title', NS).text
            description_root = get_description_root(srg)
            srgs[srg_id]['vuln_discussion'] = description_root.find('VulnDiscussion').text
            srgs[srg_id]['cci'] = \
                srg.find("xccdf-1.1:ident[@system='http://cyber.mil/cci']", NS).text
            srgs[srg_id]['fix'] = srg.find('xccdf-1.1:fix', NS).text
            srgs[srg_id]['check'] = srg.find('xccdf-1.1:description', NS).text
            srgs[srg_id]['ia_controls'] = description_root.find('IAControls').text
    return srgs


def handle_rule_yaml(product: str, rule_dir: str, env_yaml: dict) -> ssg.build_yaml.Rule:
    rule_file = ssg.rules.get_rule_dir_yaml(rule_dir)

    rule_yaml = ssg.build_yaml.Rule.from_yaml(rule_file, env_yaml=env_yaml)
    rule_yaml.normalize(product)

    return rule_yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--control', type=str, action="store", required=True,
                        help="The control file to parse")
    parser.add_argument('-o', '--output', type=str, help="The path to the output",
                        default=OUTPUT)
    parser.add_argument("-r", "--root", type=str, action="store", default=SSG_ROOT,
                        help=f"Path to SSG root directory (defaults to {SSG_ROOT})")
    parser.add_argument("-j", "--json", type=str, action="store", default=RULES_JSON,
                        help="Path to the rules_dir.json (defaults to build/stig_control.json)")
    parser.add_argument("-p", "--product", type=str, action="store", required=True,
                        help="What product to get STIGs for")
    parser.add_argument("-b", "--build-config-yaml", default=BUILD_CONFIG,
                        help="YAML file with information about the build configuration. ")
    parser.add_argument("-m", "--manual", type=str, action="store",
                        help="Path to XML XCCDF manual file to use as the source of the SRGs",
                        default=SRG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    control_full_path = pathlib.Path.joinpath(pathlib.Path('..'),
                                              pathlib.Path(args.control)).absolute()
    if not pathlib.Path.exists(control_full_path):
        sys.stderr.write(f"Unable to find control file {control_full_path}\n")
        exit(1)
    srgs = get_srg_dict(args.manual)
    control_yaml = ssg.yaml.open_raw(control_full_path)
    with open(args.json, 'r') as json_file:
        rule_json = json.load(json_file)

    full_output = pathlib.Path(args.output)
    with open(full_output, 'w') as csv_file:
        csv_writer = setup_csv_writer(csv_file)

        product_dir = os.path.join(args.root, "products", args.product)
        product_yaml_path = os.path.join(product_dir, "product.yml")
        env_yaml = ssg.environment.open_environment(args.build_config_yaml, str(product_yaml_path))

        for item in control_yaml['controls']:
            control = ssg.controls.Control.from_control_dict(item)
            for rule in control.selections:
                row = dict()
                srg_id = item['id']
                srg = srgs[srg_id]
                row['SRGID'] = srg_id
                row['CCI'] = srg['cci']
                row['SRG Requirement'] = srg['title']
                row['SRG VulDiscussion'] = srg['vuln_discussion']
                row['SRG Check'] = srg['check']
                row['SRG Fix'] = srg['fix']
                row['Severity'] = srg['severity']
                row['IA Control'] = srg['ia_controls']
                rule_object = handle_rule_yaml(args.product, rule_json[rule]['dir'], env_yaml)
                row['Fix'] = rule_object.ocil
                csv_writer.writerow(row)
        print(f"File written to {full_output}")


def setup_csv_writer(csv_file: _io.TextIOWrapper) -> csv.DictWriter:
    headers = ['IA Control', 'CCI', 'SRGID', 'SRG Requirement', 'SRG VulDiscussion',
               'VulDiscussion', 'Status', 'SRG Check', 'Check', 'SRG Fix', 'Fix',
               'Severity', 'Mitigation', 'Artifact Description', 'Status Justification']
    csv_writer = csv.DictWriter(csv_file, headers)
    csv_writer.writeheader()
    return csv_writer


if __name__ == '__main__':
    main()
