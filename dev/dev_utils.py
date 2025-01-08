### This is a collection of code snippets etc. useful when developing, e.g. exploring the UI of the Android app


def get_view_structure(self):
    self.vc.dump()

    # First, collect all views into a map
    views = self.vc.getViewsById()
    view_map = {}

    # First pass: collect all views and their properties
    for view_id in views:
        view = self.vc.findViewById(view_id)
        view_map[view_id] = {
            "id": view_id,
            "class": view.map.get("class", ""),
            "text": view.map.get("text", ""),
            "content-desc": view.map.get("content-desc", ""),
            "resource-id": view.map.get("resource-id", ""),
            "bounds": view.map.get("bounds", ""),
            "children": [],
            "parent": None,
        }

    # Second pass: build parent-child relationships
    tree = {}
    for view_id in views:
        view = self.vc.findViewById(view_id)
        parent = view.getParent()
        if parent:
            parent_id = None
            # Find parent's id in our map
            for pid in view_map:
                if self.vc.findViewById(pid) == parent:
                    parent_id = pid
                    break
            if parent_id:
                view_map[view_id]["parent"] = parent_id
                view_map[parent_id]["children"].append(view_id)
        else:
            # This is a root node
            tree[view_id] = view_map[view_id]

    # Convert the tree to a nested dictionary structure
    def build_dict_tree(node_id):
        node = view_map[node_id].copy()
        # Convert children array of IDs to array of nested nodes
        children = node["children"]
        node["children"] = [build_dict_tree(child_id) for child_id in children]
        return node

    # Build final tree structure
    final_tree = {root_id: build_dict_tree(root_id) for root_id in tree}

    # Convert to JSON and print
    import json

    json_tree = json.dumps(final_tree, indent=2, ensure_ascii=False)
    print(json_tree)
