import itertools
import typing as t

from . import nodes
from .visitor import NodeVisitor

if t.TYPE_CHECKING:
    import typing_extensions as te

VAR_LOAD_PARAMETER = "param"
VAR_LOAD_RESOLVE = "resolve"
VAR_LOAD_ALIAS = "alias"
VAR_LOAD_UNDEFINED = "undefined"


def find_symbols(
    nodes: t.Iterable[nodes.Node], parent_symbols: t.Optional["Symbols"] = None
) -> "Symbols":
    sym = Symbols(parent=parent_symbols)
    visitor = FrameSymbolVisitor(sym)
    for node in nodes:
        visitor.visit(node)
    return sym


def symbols_for_node(
    node: nodes.Node, parent_symbols: t.Optional["Symbols"] = None
) -> "Symbols":
    sym = Symbols(parent=parent_symbols)
    sym.analyze_node(node)
    return sym


# Stands for every name, it is not a valid identifier.
_ALL_NAMES = "*"


def _walk(node: nodes.Node) -> t.Iterator[nodes.Node]:
    """Yield the node and the nodes below it, except the bodies of
    unscoped blocks: a block is a function of its own that gets the
    template context, not the variables of the frame around it.
    """
    yield node

    for child in node.iter_child_nodes():
        if not (isinstance(child, nodes.Block) and not child.scoped):
            yield from _walk(child)


def _scan(node: nodes.Node) -> t.Set[str]:
    """Return the names that the node or a node below it loads, or
    ``{_ALL_NAMES}`` if it gives the variables of the frame to code that
    is not analysed here: an include or import with context, or a
    derived context reference.
    """
    rv: t.Set[str] = set()

    for child in _walk(node):
        if isinstance(child, nodes.NSRef) or (
            isinstance(child, nodes.Name) and child.ctx == "load"
        ):
            rv.add(child.name)
        elif isinstance(child, (nodes.Include, nodes.Import, nodes.FromImport)):
            if child.with_context:
                return {_ALL_NAMES}
        elif isinstance(child, nodes.DerivedContextReference):
            return {_ALL_NAMES}

    return rv


def _find_frame_loads(node: nodes.Node) -> t.Set[str]:
    """Return the names that a nested frame, or an include or import
    with context, may load from the frame it runs in. Loop and with
    targets are names of the nested frame.
    """
    own: t.Set[str] = set()
    outer: t.Sequence[nodes.Node] = ()
    inner: t.Sequence[nodes.Node]

    if isinstance(node, nodes.For):
        own = set(_find_targets(node.target))
        inner = [*node.body, *([node.test] if node.test is not None else [])]
        outer = [node.iter, *node.else_]
    elif isinstance(node, nodes.With):
        own = {name for target in node.targets for name in _find_targets(target)}
        inner = node.body
        outer = node.values
    else:
        inner = [node]

    rv: t.Set[str] = set()

    for child in inner:
        rv.update(_scan(child) - own)

    for child in outer:
        rv.update(_scan(child))

    return {_ALL_NAMES} if _ALL_NAMES in rv else rv


def _find_targets(node: nodes.Node) -> t.Iterator[str]:
    """Yield the names that an assignment target stores."""
    for child in itertools.chain([node], node.find_all(nodes.Name)):
        if isinstance(child, nodes.Name) and child.ctx in ("store", "param"):
            yield child.name


def _find_closure_loads(node: nodes.Node) -> t.Set[str]:
    """Return the names that macros and call blocks below the node load
    from outside. Such a closure can be kept and called at any later
    time, so it may see a name of the function before it is set.
    """
    rv: t.Set[str] = set()

    for closure in _walk(node):
        if closure is node or not isinstance(closure, (nodes.Macro, nodes.CallBlock)):
            continue

        params = {arg.name for arg in closure.args}

        for child in closure.body:
            rv.update(_scan(child) - params)

        for child in closure.defaults:
            rv.update(_scan(child))

    return {_ALL_NAMES} if _ALL_NAMES in rv else rv


class _Function:
    """Facts about the function that a frame is compiled into. They are
    only needed for names that are set in all branches of an if block, so
    they are computed when first asked for.
    """

    def __init__(self, node: t.Optional[nodes.Node]) -> None:
        self.node = node
        self._loads: t.Dict[nodes.Node, t.Set[str]] = {}
        self._closure_loads: t.Optional[t.Set[str]] = None

    def loads(self, node: nodes.Node) -> t.Set[str]:
        if node not in self._loads:
            self._loads[node] = _find_frame_loads(node)

        return self._loads[node]

    def closure_loads(self) -> t.Set[str]:
        if self._closure_loads is None:
            if self.node is None:
                self._closure_loads = set()
            else:
                self._closure_loads = _find_closure_loads(self.node)

        return self._closure_loads


class Symbols:
    def __init__(
        self, parent: t.Optional["Symbols"] = None, level: t.Optional[int] = None
    ) -> None:
        if level is None:
            if parent is None:
                level = 0
            else:
                level = parent.level + 1

        self.level: int = level
        self.parent = parent
        self.refs: t.Dict[str, str] = {}
        self.loads: t.Dict[str, t.Any] = {}
        self.stores: t.Set[str] = set()
        # Frames that run inside this frame, with the names stored before.
        self.nested_frames: t.List[t.Tuple[nodes.Node, t.FrozenSet[str]]] = []
        # Load targets whose value is replaced on every path before it is
        # used. They are still loaded, but meta does not report them.
        self.unused_loads: t.Set[str] = set()
        self.function: _Function = (
            _Function(None) if parent is None else parent.function
        )

    def analyze_node(self, node: nodes.Node, **kwargs: t.Any) -> None:
        # Macros and call blocks, and frames without a parent, are
        # compiled to functions of their own.
        if self.parent is None or isinstance(node, (nodes.Macro, nodes.CallBlock)):
            self.function = _Function(node)

        visitor = RootVisitor(self)
        visitor.visit(node, **kwargs)

    def _define_ref(
        self, name: str, load: t.Optional[t.Tuple[str, t.Optional[str]]] = None
    ) -> str:
        ident = f"l_{self.level}_{name}"
        self.refs[name] = ident
        if load is not None:
            self.loads[ident] = load
        return ident

    def find_load(self, target: str) -> t.Optional[t.Any]:
        if target in self.loads:
            return self.loads[target]

        if self.parent is not None:
            return self.parent.find_load(target)

        return None

    def find_ref(self, name: str) -> t.Optional[str]:
        if name in self.refs:
            return self.refs[name]

        if self.parent is not None:
            return self.parent.find_ref(name)

        return None

    def ref(self, name: str) -> str:
        rv = self.find_ref(name)
        if rv is None:
            raise AssertionError(
                "Tried to resolve a name to a reference that was"
                f" unknown to the frame ({name!r})"
            )
        return rv

    def copy(self) -> "te.Self":
        rv = object.__new__(self.__class__)
        rv.__dict__.update(self.__dict__)
        rv.refs = self.refs.copy()
        rv.loads = self.loads.copy()
        rv.stores = self.stores.copy()
        rv.nested_frames = self.nested_frames.copy()
        rv.unused_loads = self.unused_loads.copy()
        return rv

    def store(self, name: str) -> None:
        self.stores.add(name)

        # If we have not see the name referenced yet, we need to figure
        # out what to set it to.
        if name not in self.refs:
            # If there is a parent scope we check if the name has a
            # reference there.  If it does it means we might have to alias
            # to a variable there.
            if self.parent is not None:
                outer_ref = self.parent.find_ref(name)
                if outer_ref is not None:
                    self._define_ref(name, load=(VAR_LOAD_ALIAS, outer_ref))
                    return

            # Otherwise we can just set it to undefined.
            self._define_ref(name, load=(VAR_LOAD_UNDEFINED, None))

    def declare_parameter(self, name: str) -> str:
        self.stores.add(name)
        return self._define_ref(name, load=(VAR_LOAD_PARAMETER, None))

    def load(self, name: str) -> None:
        if self.find_ref(name) is None:
            self._define_ref(name, load=(VAR_LOAD_RESOLVE, name))

    def nested_frame(self, node: nodes.Node) -> None:
        """Remember a nested frame, or an include or import that gets the
        variables of this frame, that runs at this point. It can see the
        names of this frame that are not stored yet.
        """
        self.nested_frames.append((node, frozenset(self.stores)))

    def _loaded_early(self, name: str, branch_symbols: t.Sequence["Symbols"]) -> bool:
        """Check if a macro or call block, or a nested frame that runs
        before a branch stores the name, may load it.
        """
        closure_loads = self.function.closure_loads()

        if name in closure_loads or _ALL_NAMES in closure_loads:
            return True

        for branch in branch_symbols:
            for node, stored in branch.nested_frames:
                if name not in stored:
                    loads = self.function.loads(node)

                    if name in loads or _ALL_NAMES in loads:
                        return True

        return False

    def branch_update(self, branch_symbols: t.Sequence["Symbols"]) -> None:
        stores: t.Set[str] = set()

        for branch in branch_symbols:
            stores.update(branch.stores)

        stores.difference_update(self.stores)
        known_frames = len(self.nested_frames)

        for sym in branch_symbols:
            self.refs.update(sym.refs)
            self.loads.update(sym.loads)
            self.stores.update(sym.stores)
            self.nested_frames.extend(sym.nested_frames[known_frames:])

        for name in stores:
            target = self.find_ref(name)
            assert target is not None, "should not happen"

            # A branch that stores the name before loading it leaves the
            # load as undefined. If every branch does that, and no nested
            # frame or macro loads the name earlier, the value from before
            # the branches is never used. It is loaded anyway, as a frame
            # that shares the variable may see it, but meta ignores it.
            if all(
                branch.loads.get(target) == (VAR_LOAD_UNDEFINED, None)
                or target in branch.unused_loads
                for branch in branch_symbols
            ) and not self._loaded_early(name, branch_symbols):
                self.unused_loads.add(target)

            if self.parent is not None:
                outer_target = self.parent.find_ref(name)
                if outer_target is not None:
                    self.loads[target] = (VAR_LOAD_ALIAS, outer_target)
                    continue
            self.loads[target] = (VAR_LOAD_RESOLVE, name)

    def dump_stores(self) -> t.Dict[str, str]:
        rv: t.Dict[str, str] = {}
        node: t.Optional[Symbols] = self

        while node is not None:
            for name in sorted(node.stores):
                if name not in rv:
                    rv[name] = self.find_ref(name)  # type: ignore

            node = node.parent

        return rv

    def dump_param_targets(self) -> t.Set[str]:
        rv = set()
        node: t.Optional[Symbols] = self

        while node is not None:
            for target, (instr, _) in self.loads.items():
                if instr == VAR_LOAD_PARAMETER:
                    rv.add(target)

            node = node.parent

        return rv


class RootVisitor(NodeVisitor):
    def __init__(self, symbols: "Symbols") -> None:
        self.sym_visitor = FrameSymbolVisitor(symbols)

    def _simple_visit(self, node: nodes.Node, **kwargs: t.Any) -> None:
        for child in node.iter_child_nodes():
            self.sym_visitor.visit(child)

    visit_Template = _simple_visit
    visit_Block = _simple_visit
    visit_Macro = _simple_visit
    visit_FilterBlock = _simple_visit
    visit_Scope = _simple_visit
    visit_If = _simple_visit
    visit_ScopedEvalContextModifier = _simple_visit

    def visit_AssignBlock(self, node: nodes.AssignBlock, **kwargs: t.Any) -> None:
        for child in node.body:
            self.sym_visitor.visit(child)

    def visit_CallBlock(self, node: nodes.CallBlock, **kwargs: t.Any) -> None:
        for child in node.iter_child_nodes(exclude=("call",)):
            self.sym_visitor.visit(child)

    def visit_OverlayScope(self, node: nodes.OverlayScope, **kwargs: t.Any) -> None:
        for child in node.body:
            self.sym_visitor.visit(child)

    def visit_For(
        self, node: nodes.For, for_branch: str = "body", **kwargs: t.Any
    ) -> None:
        if for_branch == "body":
            self.sym_visitor.visit(node.target, store_as_param=True)
            branch = node.body
        elif for_branch == "else":
            branch = node.else_
        elif for_branch == "test":
            self.sym_visitor.visit(node.target, store_as_param=True)
            if node.test is not None:
                self.sym_visitor.visit(node.test)
            return
        else:
            raise RuntimeError("Unknown for branch")

        if branch:
            for item in branch:
                self.sym_visitor.visit(item)

    def visit_With(self, node: nodes.With, **kwargs: t.Any) -> None:
        for target in node.targets:
            self.sym_visitor.visit(target)
        for child in node.body:
            self.sym_visitor.visit(child)

    def generic_visit(self, node: nodes.Node, *args: t.Any, **kwargs: t.Any) -> None:
        raise NotImplementedError(f"Cannot find symbols for {type(node).__name__!r}")


class FrameSymbolVisitor(NodeVisitor):
    """A visitor for `Frame.inspect`."""

    def __init__(self, symbols: "Symbols") -> None:
        self.symbols = symbols

    def visit_Name(
        self, node: nodes.Name, store_as_param: bool = False, **kwargs: t.Any
    ) -> None:
        """All assignments to names go through this function."""
        if store_as_param or node.ctx == "param":
            self.symbols.declare_parameter(node.name)
        elif node.ctx == "store":
            self.symbols.store(node.name)
        elif node.ctx == "load":
            self.symbols.load(node.name)

    def visit_NSRef(self, node: nodes.NSRef, **kwargs: t.Any) -> None:
        self.symbols.load(node.name)

    def visit_If(self, node: nodes.If, **kwargs: t.Any) -> None:
        self.visit(node.test, **kwargs)
        original_symbols = self.symbols

        def inner_visit(nodes: t.Iterable[nodes.Node]) -> "Symbols":
            self.symbols = rv = original_symbols.copy()

            for subnode in nodes:
                self.visit(subnode, **kwargs)

            self.symbols = original_symbols
            return rv

        body_symbols = inner_visit(node.body)
        # Each elif is a branch of its own, its test runs before its body.
        elif_symbols = [inner_visit([elif_.test, *elif_.body]) for elif_ in node.elif_]
        else_symbols = inner_visit(node.else_ or ())
        self.symbols.branch_update([body_symbols, *elif_symbols, else_symbols])

    def visit_Macro(self, node: nodes.Macro, **kwargs: t.Any) -> None:
        self.symbols.store(node.name)

    def visit_Include(self, node: nodes.Include, **kwargs: t.Any) -> None:
        self.generic_visit(node, **kwargs)

        if node.with_context:
            self.symbols.nested_frame(node)

    def visit_Import(self, node: nodes.Import, **kwargs: t.Any) -> None:
        self.generic_visit(node, **kwargs)

        if node.with_context:
            self.symbols.nested_frame(node)

        self.symbols.store(node.target)

    def visit_FromImport(self, node: nodes.FromImport, **kwargs: t.Any) -> None:
        self.generic_visit(node, **kwargs)

        if node.with_context:
            self.symbols.nested_frame(node)

        for name in node.names:
            if isinstance(name, tuple):
                self.symbols.store(name[1])
            else:
                self.symbols.store(name)

    def visit_Assign(self, node: nodes.Assign, **kwargs: t.Any) -> None:
        """Visit assignments in the correct order."""
        self.visit(node.node, **kwargs)
        self.visit(node.target, **kwargs)

    def visit_For(self, node: nodes.For, **kwargs: t.Any) -> None:
        """Visiting stops at for blocks.  However the block sequence
        is visited as part of the outer scope.
        """
        self.symbols.nested_frame(node)
        self.visit(node.iter, **kwargs)

    def visit_CallBlock(self, node: nodes.CallBlock, **kwargs: t.Any) -> None:
        self.visit(node.call, **kwargs)

    def visit_FilterBlock(self, node: nodes.FilterBlock, **kwargs: t.Any) -> None:
        self.symbols.nested_frame(node)
        self.visit(node.filter, **kwargs)

    def visit_With(self, node: nodes.With, **kwargs: t.Any) -> None:
        self.symbols.nested_frame(node)

        for target in node.values:
            self.visit(target)

    def visit_AssignBlock(self, node: nodes.AssignBlock, **kwargs: t.Any) -> None:
        """Stop visiting at block assigns."""
        self.symbols.nested_frame(node)
        self.visit(node.target, **kwargs)

    def visit_Scope(self, node: nodes.Scope, **kwargs: t.Any) -> None:
        """Stop visiting at scopes."""
        self.symbols.nested_frame(node)

    def visit_Block(self, node: nodes.Block, **kwargs: t.Any) -> None:
        """Stop visiting at blocks."""
        if node.scoped:
            self.symbols.nested_frame(node)

    def visit_OverlayScope(self, node: nodes.OverlayScope, **kwargs: t.Any) -> None:
        """Do not visit into overlay scopes."""
        self.symbols.nested_frame(node)

    def visit_DerivedContextReference(
        self, node: nodes.DerivedContextReference, **kwargs: t.Any
    ) -> None:
        self.symbols.nested_frame(node)
