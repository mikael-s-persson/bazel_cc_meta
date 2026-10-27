import argparse
import xml.etree.ElementTree as ElementTree
from copy import deepcopy


def fix_namespace_tags(tree, group_name):
    root = tree.getroot()

    for compound in root.findall("compound"):
        # Target the shared namespace
        if compound.get("kind") != "namespace":
            continue
        ns_name_node = compound.find("name")
        if ns_name_node is None:
            continue
        # Change the 'namespace' scope to 'file' scope
        compound.set("kind", "file")
        dup_members = []
        for member in compound.findall("member"):
            name_node = member.find("name")
            # Add namespace qualified name to the member
            if name_node is not None and not name_node.text.startswith(
                f"{ns_name_node.text}::"
            ):
                qmem_node = deepcopy(member)
                qname_node = qmem_node.find("name")
                qname_node.text = f"{ns_name_node.text}::{name_node.text}"
                dup_members.append(qmem_node)
        for dup_mem in dup_members:
            compound.append(dup_mem)
        ns_name_node.text = "namespace" + ns_name_node.text


def main():
    parser = argparse.ArgumentParser(
        prog="CleanDoxygenTagFile",
        description="Cleans doxygen a tag file to make it work as a module.",
    )
    parser.add_argument("--input", required=True, help="Input tag file (xml).")
    parser.add_argument("--output", required=True, help="Output tag file (xml).")
    parser.add_argument("--group-name", required=True, help="Group name for this tag.")
    args = parser.parse_args()

    tree = ElementTree.parse(args.input)

    fix_namespace_tags(tree, args.group_name)

    tree.write(args.output, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
