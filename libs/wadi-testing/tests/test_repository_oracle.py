"""The repository call-site oracle (§5.2.17, design success criterion 4, C4).

The oracle reads source and never an export, so these tests feed it Java and
nothing else: small inline snippets for each shape it claims to see, then the
`spring-data-crud-matrix` fixture, whose per-file counts were taken by opening
every file by hand.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from wadi_testing.measure.repository_oracle import RepositoryCallSite, load_sites, main, scan

JOERN_PLATFORM = Path(__file__).resolve().parents[3] / "joern-platform"
CRUD_MATRIX = JOERN_PLATFORM / "fixtures" / "spring-data-crud-matrix"

_ORDER_REPOSITORY = """\
package com.acme.repo;

import org.springframework.data.jpa.repository.JpaRepository;

public interface OrderRepository extends JpaRepository<Order, String> {
}
"""


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestOneRepositoryCall:
    def test_a_call_on_a_repository_field_is_one_site(self, tmp_path: Path) -> None:
        _write(tmp_path, "src/main/java/com/acme/repo/OrderRepository.java", _ORDER_REPOSITORY)
        _write(
            tmp_path,
            "src/main/java/com/acme/web/OrderController.java",
            """\
package com.acme.web;

public class OrderController {
    private final OrderRepository orderRepository;

    public Order show(String id) {
        return orderRepository.findById(id).orElseThrow();
    }
}
""",
        )

        report = scan(tmp_path)

        assert report.sites == [
            RepositoryCallSite(
                module=".",
                file="src/main/java/com/acme/web/OrderController.java",
                line=7,
                repository="OrderRepository",
                receiver="orderRepository",
                method="findById",
                enclosing_class="OrderController",
                enclosing_method="show",
                in_lambda=False,
            )
        ]


def _controller(tmp_path: Path, body: str, *, fields: str = "") -> list[RepositoryCallSite]:
    """Scan one controller holding ``body``, next to `OrderRepository`."""
    _write(tmp_path, "src/main/java/com/acme/repo/OrderRepository.java", _ORDER_REPOSITORY)
    _write(
        tmp_path,
        "src/main/java/com/acme/web/OrderController.java",
        "package com.acme.web;\n\npublic class OrderController {\n"
        + (fields or "    private final OrderRepository orderRepository;\n")
        + body
        + "}\n",
    )
    return scan(tmp_path).sites


class TestCommentsAndStrings:
    def test_a_call_in_a_comment_or_a_string_is_not_a_site(self, tmp_path: Path) -> None:
        sites = _controller(
            tmp_path,
            '''\
    /** Javadoc naming orderRepository.findAll() is prose. */
    public void m() {
        // orderRepository.deleteAll();
        /* orderRepository.deleteById("x");
           orderRepository.count(); */
        String s = "orderRepository.save(o)";
        String block = """
            orderRepository.flush();
            """;
        char quote = '"';
        String url = "http://x"; orderRepository.findById("a");
    }
''',
        )

        assert [(site.line, site.method) for site in sites] == [(15, "findById")]


class TestWhichInterfacesAreRepositories:
    def test_a_repository_reached_through_a_project_base_interface(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "src/main/java/com/acme/repo/BaseRepository.java",
            """\
package com.acme.repo;

import org.springframework.data.jpa.repository.JpaRepository;

public interface BaseRepository<E> extends JpaRepository<E, Long> {
}
""",
        )
        _write(
            tmp_path,
            "src/main/java/com/acme/repo/IssueRepository.java",
            "package com.acme.repo;\n\n"
            "public interface IssueRepository extends BaseRepository<Issue> {\n}\n",
        )
        _write(
            tmp_path,
            "src/main/java/com/acme/repo/IssueRepositoryCustom.java",
            "package com.acme.repo;\n\npublic interface IssueRepositoryCustom {\n}\n",
        )
        _write(
            tmp_path,
            "src/main/java/com/acme/web/IssueController.java",
            """\
package com.acme.web;

public class IssueController {
    private final IssueRepository issues;
    private final IssueRepositoryCustom custom;
    private final BaseRepository<Issue> base;

    public Object m() {
        custom.archive();
        base.count();
        return issues.findAllByIdIn(ids);
    }
}
""",
        )

        report = scan(tmp_path)

        assert report.repositories == ["BaseRepository", "IssueRepository"]
        assert [(s.repository, s.method) for s in report.sites] == [
            ("BaseRepository", "count"),
            ("IssueRepository", "findAllByIdIn"),
        ]

    def test_a_marker_counts_only_when_it_is_spring_datas(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "src/main/java/com/acme/repo/PetRepository.java",
            """\
package com.acme.repo;

import org.springframework.data.repository.reactive.ReactiveCrudRepository;

public interface PetRepository extends ReactiveCrudRepository<Pet, String> {
}
""",
        )
        _write(
            tmp_path,
            "src/main/java/com/acme/git/History.java",
            """\
package com.acme.git;

import org.eclipse.jgit.lib.Repository;
import org.springframework.data.repository.CrudRepository;

public class History {
    private final Repository git;
    private final CrudRepository<Pet, String> pets;
    private final PetRepository reactive;

    public void m() {
        git.close();
        pets.count();
        reactive.findById(id);
    }
}
""",
        )

        assert [(s.repository, s.method) for s in scan(tmp_path).sites] == [
            ("CrudRepository", "count"),
            ("PetRepository", "findById"),
        ]


class TestDefaultMethods:
    def test_a_receiverless_call_in_a_repository_default_method_is_a_site(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            "src/main/java/com/acme/repo/OrderRepository.java",
            """\
package com.acme.repo;

import static java.util.Objects.requireNonNull;

import org.springframework.data.jpa.repository.JpaRepository;

public interface OrderRepository extends JpaRepository<Order, String> {

    List<Order> findByStatus(String status);

    default Order touch(String id) {
        requireNonNull(id);
        Order order = findById(id).orElse(new Order(id));
        return this.save(order);
    }
}
""",
        )

        assert [
            (s.line, s.receiver, s.method, s.enclosing_method) for s in scan(tmp_path).sites
        ] == [
            (13, "", "findById", "touch"),
            (14, "this", "save", "touch"),
        ]


class TestRepositoryVariables:
    def test_injected_fields_parameters_and_locals_are_all_receivers(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "src/main/java/com/acme/repo/PetRepository.java",
            "package com.acme.repo;\n\n"
            "import org.springframework.data.mongodb.repository.MongoRepository;\n\n"
            "public interface PetRepository extends MongoRepository<Pet, String> {\n}\n",
        )
        sites = _controller(
            tmp_path,
            fields="""\
    @Autowired
    private PetRepository pets;
    private final OrderRepository orderRepository;

    public OrderController(
            @Qualifier("primary") OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }
""",
            body="""\
    public void a(PetRepository repository) {
        this.orderRepository.deleteById(id);
        pets.count();
        repository.findAll();
    }

    public void b() {
        OrderRepository repository = orderRepository;
        repository.findAll();
    }
""",
        )

        assert [(s.enclosing_method, s.receiver, s.repository, s.method) for s in sites] == [
            ("a", "orderRepository", "OrderRepository", "deleteById"),
            ("a", "pets", "PetRepository", "count"),
            ("a", "repository", "PetRepository", "findAll"),
            ("b", "repository", "OrderRepository", "findAll"),
        ]


class TestLambdas:
    def test_a_call_in_a_lambda_body_is_a_site_marked_in_lambda(self, tmp_path: Path) -> None:
        sites = _controller(
            tmp_path,
            """\
    public void m(List<String> ids, String kind) {
        ids.forEach(id -> orderRepository.save(new Order(id)));
        orderRepository.findAll().forEach(order -> log(order));
        ids.forEach(id -> {
            orderRepository.deleteById(id);
        });
        Runnable later = () -> orderRepository.flush(), now = null;
        switch (kind) {
            case "all" -> orderRepository.deleteAll();
            default -> ids.forEach(id -> orderRepository.existsById(id));
        }
        orderRepository.count();
    }
""",
        )

        assert [(s.method, s.in_lambda, s.enclosing_method) for s in sites] == [
            ("save", True, "m"),
            ("findAll", False, "m"),
            ("deleteById", True, "m"),
            ("flush", True, "m"),
            ("deleteAll", False, "m"),
            ("existsById", True, "m"),
            ("count", False, "m"),
        ]


class TestTwoCallsOnOneLine:
    def test_each_call_is_its_own_site_in_source_order(self, tmp_path: Path) -> None:
        sites = _controller(
            tmp_path,
            """\
    public long m(String id) {
        orderRepository.save(orderRepository.findById(id).orElseThrow());
        return orderRepository.count() + orderRepository.count();
    }
""",
        )

        assert [(s.line, s.method) for s in sites] == [
            (6, "save"),
            (6, "findById"),
            (7, "count"),
            (7, "count"),
        ]


class TestWhichFilesAreRead:
    def test_test_and_build_output_trees_are_skipped_and_sites_name_their_module(
        self, tmp_path: Path
    ) -> None:
        call = (
            "package com.acme.{pkg};\n\npublic class C {{\n"
            "    private OrderRepository repo;\n"
            "    void m() {{ repo.count(); }}\n}}\n"
        )
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "orders").mkdir()
        (tmp_path / "orders" / "pom.xml").write_text("<project/>")
        _write(tmp_path, "orders/src/main/java/com/acme/OrderRepository.java", _ORDER_REPOSITORY)
        kept = {
            "orders/src/main/java/com/acme/web/C.java",
            # A PACKAGE named `build` or `target` is source, not build output.
            "orders/src/main/java/com/acme/build/C.java",
            "orders/src/main/java/com/acme/target/C.java",
            "tools/src/main/java/com/acme/C.java",
        }
        skipped = {
            "orders/src/test/java/com/acme/C.java",
            "orders/target/generated-sources/com/acme/C.java",
            "orders/build/generated/com/acme/C.java",
            "orders/.evosuite-work/src/main/java/com/acme/C.java",
        }
        for relative in kept | skipped:
            _write(tmp_path, relative, call.format(pkg="x"))

        sites = scan(tmp_path).sites

        assert {(s.module, s.file) for s in sites} == {
            ("orders", "orders/src/main/java/com/acme/web/C.java"),
            ("orders", "orders/src/main/java/com/acme/build/C.java"),
            ("orders", "orders/src/main/java/com/acme/target/C.java"),
            (".", "tools/src/main/java/com/acme/C.java"),
        }


#: Counted by opening each fixture file, one handler at a time, against the
#: flows `SpringDataCrudMatrixConformanceTest` names. Not derived from any export.
CRUD_MATRIX_SITES_PER_FILE = {
    # 41 47 53 59 65 66, the twelve statements of golden 34 (74-85), 92, 98.
    "web/InheritedAndDerivedController.java": 20,
    # 54 60 66 72, golden 11's two (78 79), golden 12's five (89-93), 102, 108.
    "web/QueryController.java": 13,
    # Two at 137 (golden 25) and one in the golden-26 lambda at 144.
    "web/SaveController.java": 20,
    "web/ShapeController.java": 8,
    "service/OrderWriter.java": 3,
    "service/OrderLookup.java": 1,
    # `repository` is declared as the generic base interface (golden 30).
    "service/AbstractArchiver.java": 1,
    # `findById` and `save` with no receiver, inside the golden-32 default method.
    "repo/OrderRepository.java": 2,
}


class TestCrudMatrixFixture:
    def test_the_site_count_per_file_matches_the_fixture(self) -> None:
        prefix = "src/main/java/com/acme/crud/"
        counts = Counter(site.file.removeprefix(prefix) for site in scan(CRUD_MATRIX).sites)

        assert dict(counts) == CRUD_MATRIX_SITES_PER_FILE

    def test_the_only_lambda_site_is_golden_26(self) -> None:
        in_lambda = [site for site in scan(CRUD_MATRIX).sites if site.in_lambda]

        assert [(s.file.rsplit("/", 1)[-1], s.line, s.method) for s in in_lambda] == [
            ("SaveController.java", 144, "save")
        ]


class TestCommandLine:
    def test_json_holds_every_site_and_the_summary_counts_them(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "sites.json"

        assert main([str(CRUD_MATRIX), "--json", str(out)]) == 0

        written = json.loads(out.read_text())
        assert load_sites(out) == scan(CRUD_MATRIX).sites
        assert written["totals"] == {
            "sites": 68,
            "in_lambda": 1,
            "method_references": 0,
            "by_module": {".": 68},
        }
        printed = capsys.readouterr().out
        assert "src/main/java/com/acme/crud/web/SaveController.java:144" in printed
        assert "sites: 68" in printed

    def test_a_method_reference_is_counted_apart_from_the_sites(self, tmp_path: Path) -> None:
        _write(tmp_path, "src/main/java/com/acme/repo/OrderRepository.java", _ORDER_REPOSITORY)
        _write(
            tmp_path,
            "src/main/java/com/acme/web/C.java",
            "package com.acme.web;\n\npublic class C {\n"
            "    private OrderRepository orderRepository;\n"
            "    void m(List<Order> orders) { orders.forEach(orderRepository::save); }\n}\n",
        )

        report = scan(tmp_path)

        assert report.sites == []
        assert [(r.line, r.method) for r in report.method_references] == [(5, "save")]
