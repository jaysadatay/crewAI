import ast
import inspect
import textwrap


def get_possible_return_constants(function):
    try:
        source = inspect.getsource(function)
    except OSError:
        # Can't get source code
        return None
    except Exception as e:
        print(f"Error retrieving source code for function {function.__name__}: {e}")
        return None

    try:
        # Remove leading indentation
        source = textwrap.dedent(source)
        # Parse the source code into an AST
        code_ast = ast.parse(source)
    except IndentationError as e:
        print(f"IndentationError while parsing source code of {function.__name__}: {e}")
        print(f"Source code:\n{source}")
        return None
    except SyntaxError as e:
        print(f"SyntaxError while parsing source code of {function.__name__}: {e}")
        print(f"Source code:\n{source}")
        return None
    except Exception as e:
        print(f"Unexpected error while parsing source code of {function.__name__}: {e}")
        print(f"Source code:\n{source}")
        return None

    return_values = set()
    dict_definitions = {}

    class DictionaryAssignmentVisitor(ast.NodeVisitor):
        def visit_Assign(self, node):
            # Check if this assignment is assigning a dictionary literal to a variable
            if isinstance(node.value, ast.Dict) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    var_name = target.id
                    dict_values = []
                    # Extract string values from the dictionary
                    for val in node.value.values:
                        if isinstance(val, ast.Constant) and isinstance(val.value, str):
                            dict_values.append(val.value)
                        # If non-string, skip or just ignore
                    if dict_values:
                        dict_definitions[var_name] = dict_values
            self.generic_visit(node)

    class ReturnVisitor(ast.NodeVisitor):
        def visit_Return(self, node):
            # Direct string return
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                return_values.add(node.value.value)
            # Dictionary-based return, like return paths[result]
            elif isinstance(node.value, ast.Subscript):
                # Check if we're subscripting a known dictionary variable
                if isinstance(node.value.value, ast.Name):
                    var_name = node.value.value.id
                    if var_name in dict_definitions:
                        # Add all possible dictionary values
                        for v in dict_definitions[var_name]:
                            return_values.add(v)
            self.generic_visit(node)

    # First pass: identify dictionary assignments
    DictionaryAssignmentVisitor().visit(code_ast)
    # Second pass: identify returns
    ReturnVisitor().visit(code_ast)

    return list(return_values) if return_values else None


def calculate_node_levels(flow):
    levels = {}
    queue = []
    visited = set()
    pending_and_listeners = {}

    # Make all start methods at level 0
    for method_name, method in flow._methods.items():
        if hasattr(method, "__is_start_method__"):
            levels[method_name] = 0
            queue.append(method_name)

    # Breadth-first traversal to assign levels
    while queue:
        current = queue.pop(0)
        current_level = levels[current]
        visited.add(current)

        for listener_name, (condition_type, trigger_methods) in flow._listeners.items():
            if condition_type == "OR":
                if current in trigger_methods:
                    if (
                        listener_name not in levels
                        or levels[listener_name] > current_level + 1
                    ):
                        levels[listener_name] = current_level + 1
                        if listener_name not in visited:
                            queue.append(listener_name)
            elif condition_type == "AND":
                if listener_name not in pending_and_listeners:
                    pending_and_listeners[listener_name] = set()
                if current in trigger_methods:
                    pending_and_listeners[listener_name].add(current)
                if set(trigger_methods) == pending_and_listeners[listener_name]:
                    if (
                        listener_name not in levels
                        or levels[listener_name] > current_level + 1
                    ):
                        levels[listener_name] = current_level + 1
                        if listener_name not in visited:
                            queue.append(listener_name)

        # Handle router connections
        if current in flow._routers:
            router_method_name = current
            paths = flow._router_paths.get(router_method_name, [])
            for path in paths:
                for listener_name, (
                    condition_type,
                    trigger_methods,
                ) in flow._listeners.items():
                    if path in trigger_methods:
                        if (
                            listener_name not in levels
                            or levels[listener_name] > current_level + 1
                        ):
                            levels[listener_name] = current_level + 1
                            if listener_name not in visited:
                                queue.append(listener_name)

    return levels


def count_outgoing_edges(flow):
    counts = {}
    for method_name in flow._methods:
        counts[method_name] = 0
    for method_name in flow._listeners:
        _, trigger_methods = flow._listeners[method_name]
        for trigger in trigger_methods:
            if trigger in flow._methods:
                counts[trigger] += 1
    return counts


def build_ancestor_dict(flow):
    ancestors = {node: set() for node in flow._methods}
    visited = set()
    for node in flow._methods:
        if node not in visited:
            dfs_ancestors(node, ancestors, visited, flow)
    return ancestors


def dfs_ancestors(node, ancestors, visited, flow):
    if node in visited:
        return
    visited.add(node)

    # Handle regular listeners
    for listener_name, (_, trigger_methods) in flow._listeners.items():
        if node in trigger_methods:
            ancestors[listener_name].add(node)
            ancestors[listener_name].update(ancestors[node])
            dfs_ancestors(listener_name, ancestors, visited, flow)

    # Handle router methods separately
    if node in flow._routers:
        router_method_name = node
        paths = flow._router_paths.get(router_method_name, [])
        for path in paths:
            for listener_name, (_, trigger_methods) in flow._listeners.items():
                if path in trigger_methods:
                    # Only propagate the ancestors of the router method, not the router method itself
                    ancestors[listener_name].update(ancestors[node])
                    dfs_ancestors(listener_name, ancestors, visited, flow)


def is_ancestor(node, ancestor_candidate, ancestors):
    return ancestor_candidate in ancestors.get(node, set())


def build_parent_children_dict(flow):
    parent_children = {}

    # Map listeners to their trigger methods
    for listener_name, (_, trigger_methods) in flow._listeners.items():
        for trigger in trigger_methods:
            if trigger not in parent_children:
                parent_children[trigger] = []
            if listener_name not in parent_children[trigger]:
                parent_children[trigger].append(listener_name)

    # Map router methods to their paths and to listeners
    for router_method_name, paths in flow._router_paths.items():
        for path in paths:
            # Map router method to listeners of each path
            for listener_name, (_, trigger_methods) in flow._listeners.items():
                if path in trigger_methods:
                    if router_method_name not in parent_children:
                        parent_children[router_method_name] = []
                    if listener_name not in parent_children[router_method_name]:
                        parent_children[router_method_name].append(listener_name)

    return parent_children


def get_child_index(parent, child, parent_children):
    children = parent_children.get(parent, [])
    children.sort()
    return children.index(child)