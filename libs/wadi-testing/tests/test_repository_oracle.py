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

from wadi_testing.measure.repository_oracle import (
    OracleOperation,
    RepositoryCallSite,
    load_sites,
    main,
    name_operation,
    scan,
)

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
                entity="Order",
                operation=OracleOperation.READ,
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


class TestTypeVariableReceivers:
    def test_a_receiver_typed_by_a_bounded_type_parameter_is_a_repository(
        self, tmp_path: Path
    ) -> None:
        # wadi's pass reads `R repository` as its bound (review A2), so the
        # oracle must as well, or the reconciler reports a wadi-only site.
        _write(
            tmp_path,
            "src/main/java/com/acme/service/BoundedStore.java",
            """\
package com.acme.service;

import org.springframework.data.jpa.repository.JpaRepository;

public abstract class BoundedStore<R extends JpaRepository<Order, String>> {
    private final R repository;

    public List<Order> all() {
        return repository.findAll();
    }
}
""",
        )
        [site] = scan(tmp_path).sites
        assert (site.repository, site.receiver, site.method) == (
            "JpaRepository",
            "repository",
            "findAll",
        )
        assert (site.entity, site.operation) == ("Order", OracleOperation.READ)

    def test_an_unbounded_or_non_repository_type_parameter_is_not(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "src/main/java/com/acme/service/Holder.java",
            """\
package com.acme.service;

import java.util.List;

public class Holder<T, L extends List<String>> {
    private final T value;
    private final L names;

    public int size() {
        value.findAll();
        return names.size();
    }
}
""",
        )
        assert scan(tmp_path).sites == []


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


def _repositories(root: Path, *files: tuple[str, str]) -> None:
    for name, text in files:
        _write(root, f"src/main/java/com/acme/repo/{name}.java", text)


def _calls(root: Path, fields: str, body: str) -> list[RepositoryCallSite]:
    """Scan one service class holding ``fields`` and a method ``body``."""
    _write(
        root,
        "src/main/java/com/acme/web/Calls.java",
        "package com.acme.web;\n\npublic class Calls {\n"
        + fields
        + "    void m() {\n"
        + body
        + "    }\n}\n",
    )
    return scan(root).sites


_JPA = "import org.springframework.data.jpa.repository.JpaRepository;\n"


class TestEntityFromTheTypeArgument:
    """Review D6: the oracle names the entity from the repository's declared
    type argument, so a reconciled site can be compared on WHAT it touches."""

    def test_the_markers_first_argument_qualified_or_not_is_the_entity(
        self, tmp_path: Path
    ) -> None:
        _repositories(
            tmp_path,
            ("OrderRepository", _ORDER_REPOSITORY),
            (
                "AccountRepository",
                "package com.acme.repo;\n\n" + _JPA + "\npublic interface AccountRepository "
                "extends JpaRepository<com.acme.crm.Account, Long> {\n}\n",
            ),
        )

        sites = _calls(
            tmp_path,
            "    private OrderRepository orders;\n    private AccountRepository accounts;\n",
            "        orders.count();\n        accounts.count();\n",
        )

        assert [(s.repository, s.entity) for s in sites] == [
            ("OrderRepository", "Order"),
            ("AccountRepository", "Account"),
        ]

    def test_an_argument_binds_by_position_through_a_project_base_interface(
        self, tmp_path: Path
    ) -> None:
        # KeyedRepository puts the key first; JpaRepository wants the entity
        # first. Position, not the letter, decides which argument is the entity.
        _repositories(
            tmp_path,
            (
                "KeyedRepository",
                "package com.acme.repo;\n\n" + _JPA + "\npublic interface KeyedRepository<ID, E> "
                "extends JpaRepository<E, ID> {\n}\n",
            ),
            (
                "TicketRepository",
                "package com.acme.repo;\n\npublic interface TicketRepository "
                "extends KeyedRepository<String, Ticket> {\n}\n",
            ),
        )

        sites = _calls(
            tmp_path, "    private TicketRepository tickets;\n", "        tickets.findAll();\n"
        )

        assert [(s.repository, s.entity) for s in sites] == [("TicketRepository", "Ticket")]

    def test_a_variables_own_type_arguments_bind_or_leave_the_entity_unbound(
        self, tmp_path: Path
    ) -> None:
        _repositories(
            tmp_path,
            (
                "BaseRepository",
                "package com.acme.repo;\n\n" + _JPA + "\npublic interface BaseRepository<E> "
                "extends JpaRepository<E, Long> {\n}\n",
            ),
        )
        _write(
            tmp_path,
            "src/main/java/com/acme/web/Archiver.java",
            """\
package com.acme.web;

import org.springframework.data.repository.CrudRepository;

public abstract class Archiver<E> {
    private BaseRepository<Issue> issues;
    private BaseRepository<E> generic;
    private BaseRepository raw;
    private CrudRepository<Pet, String> pets;

    void m() {
        issues.count();
        generic.count();
        raw.count();
        pets.count();
    }
}
""",
        )

        sites = scan(tmp_path).sites

        # `E` is the class's own type variable and a raw type binds nothing:
        # both are unbound, never the letter `E` as if it were a class.
        assert [(s.receiver, s.entity) for s in sites] == [
            ("issues", "Issue"),
            ("generic", None),
            ("raw", None),
            ("pets", "Pet"),
        ]

    def test_a_receiverless_call_in_a_default_method_names_its_interfaces_entity(
        self, tmp_path: Path
    ) -> None:
        _repositories(
            tmp_path,
            (
                "OrderRepository",
                "package com.acme.repo;\n\n" + _JPA + "\npublic interface OrderRepository "
                "extends JpaRepository<Order, String> {\n"
                "    default void touch(String id) { save(findById(id).orElseThrow()); }\n}\n",
            ),
        )

        assert [(s.method, s.entity) for s in scan(tmp_path).sites] == [
            ("save", "Order"),
            ("findById", "Order"),
        ]


class TestOperationByName:
    """Spring Data's subject-prefix rule: a prefix counts only where the name
    ends there or continues with an uppercase letter (review B, review D6)."""

    @pytest.mark.parametrize(
        ("name", "operation"),
        [
            ("save", OracleOperation.CREATE_OR_UPDATE),
            ("saveAll", OracleOperation.CREATE_OR_UPDATE),
            ("saveAndFlush", OracleOperation.CREATE_OR_UPDATE),
            ("insert", OracleOperation.CREATE),
            ("delete", OracleOperation.DELETE),
            ("deleteAllInBatch", OracleOperation.DELETE),
            ("removeByStatus", OracleOperation.DELETE),
            ("findById", OracleOperation.READ),
            ("getReferenceById", OracleOperation.READ),
            ("readByName", OracleOperation.READ),
            ("queryByName", OracleOperation.READ),
            ("searchByName", OracleOperation.READ),
            ("streamAllBy", OracleOperation.READ),
            ("count", OracleOperation.READ),
            ("existsById", OracleOperation.READ),
            ("flush", OracleOperation.NONE),
            # The prefix continues in lowercase: not the verb it starts with.
            ("deleted", OracleOperation.UNKNOWN),
            ("saved", OracleOperation.UNKNOWN),
            ("finder", OracleOperation.UNKNOWN),
            ("counter", OracleOperation.UNKNOWN),
            # `insert` is a whole name, and a name outside the table is not guessed.
            ("insertAll", OracleOperation.UNKNOWN),
            ("flushAll", OracleOperation.UNKNOWN),
            ("sumOpen", OracleOperation.UNKNOWN),
            ("archiveOld", OracleOperation.UNKNOWN),
        ],
    )
    def test_the_name_table(self, name: str, operation: OracleOperation) -> None:
        assert name_operation(name) is operation


_ANNOTATED_REPOSITORY = """\
package com.acme.repo;

import com.acme.repo.Audited;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.NativeQuery;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.query.Procedure;
import org.springframework.data.mongodb.repository.Update;
import org.springframework.transaction.annotation.Transactional;

public interface OrderRepository extends JpaRepository<Order, String> {

    @Query("select o from Order o where o.status = ?1")
    List<Order> findInStatus(String status);

    @NativeQuery("select * from orders")
    List<Order> findNative();

    @Modifying
    int deleteStale();

    @Update("{ '$set': { 'status': ?1 } }")
    void findAndSetStatus(String id, String status);

    @Procedure("archive")
    void findArchived();

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Transactional
    Optional<Order> findLockedById(String id);

    @Audited
    List<Order> findByStatus(String status);

    default Order findAndTouch(String id) {
        return findById(id).orElseThrow();
    }
}
"""


class TestOperationFromTheDeclaration:
    """The repository method's declaration can take the verb away from its name."""

    def test_query_unknown_and_neutral_annotations(self, tmp_path: Path) -> None:
        _repositories(tmp_path, ("OrderRepository", _ANNOTATED_REPOSITORY))

        sites = _calls(
            tmp_path,
            "    private OrderRepository orders;\n",
            "        orders.findInStatus(s);\n"
            "        orders.findNative();\n"
            "        orders.deleteStale();\n"
            "        orders.findAndSetStatus(id, s);\n"
            "        orders.findArchived();\n"
            "        orders.findLockedById(id);\n"
            "        orders.findByStatus(s);\n"
            "        orders.findAndTouch(id);\n"
            "        orders.findById(id);\n",
        )

        assert [(s.method, s.operation) for s in sites if s.receiver == "orders"] == [
            # The verb is in query text, which the oracle does not read.
            ("findInStatus", OracleOperation.QUERY),
            ("findNative", OracleOperation.QUERY),
            ("deleteStale", OracleOperation.QUERY),
            # A persistence annotation outside the neutral list takes the verb
            # away from the name: Mongo `@Update`, JPA `@Procedure`.
            ("findAndSetStatus", OracleOperation.UNKNOWN),
            ("findArchived", OracleOperation.UNKNOWN),
            # `@Lock` only tunes the read; `@Transactional` is not a Spring Data
            # annotation; `@Audited` is the project's own. The name decides.
            ("findLockedById", OracleOperation.READ),
            ("findByStatus", OracleOperation.READ),
            # A default method's body is project code, whatever it is called.
            ("findAndTouch", OracleOperation.UNKNOWN),
            # Declared by Spring Data, not the project: the name decides.
            ("findById", OracleOperation.READ),
        ]

    def test_an_annotation_counts_only_when_it_is_spring_datas_or_hibernates(
        self, tmp_path: Path
    ) -> None:
        _repositories(
            tmp_path,
            (
                "OrderRepository",
                "package com.acme.repo;\n\n"
                "import com.acme.search.Query;\n" + _JPA + "\npublic interface OrderRepository "
                "extends JpaRepository<Order, String> {\n"
                '    @Query("indexed")\n    List<Order> findByStatus(String status);\n\n'
                '    @org.springframework.data.jpa.repository.Query("select o from Order o")\n'
                "    List<Order> findEverything();\n\n"
                '    @org.hibernate.annotations.SQLSelect(sql = "select 1")\n'
                "    List<Order> findRaw();\n}\n",
            ),
        )

        sites = _calls(
            tmp_path,
            "    private OrderRepository orders;\n",
            "        orders.findByStatus(s);\n        orders.findEverything();\n"
            "        orders.findRaw();\n",
        )

        assert [(s.method, s.operation) for s in sites] == [
            ("findByStatus", OracleOperation.READ),
            ("findEverything", OracleOperation.QUERY),
            ("findRaw", OracleOperation.UNKNOWN),
        ]

    def test_the_nearest_declaration_wins_and_a_base_declaration_counts(
        self, tmp_path: Path
    ) -> None:
        # A sub-interface's `@Query` redeclaration overrides the base's plain
        # one, and a method only the base declares is still read from there.
        _repositories(
            tmp_path,
            (
                "BaseRepository",
                "package com.acme.repo;\n\n" + _JPA + "\npublic interface BaseRepository<E> "
                "extends JpaRepository<E, Long> {\n"
                "    List<E> findByName(String name);\n\n"
                "    @org.springframework.data.jpa.repository.Modifying\n"
                "    int deleteOld();\n}\n",
            ),
            (
                "IssueRepository",
                "package com.acme.repo;\n\n"
                "import org.springframework.data.jpa.repository.Query;\n\n"
                "public interface IssueRepository extends BaseRepository<Issue> {\n"
                '    @Query("select i from Issue i where i.name = ?1")\n'
                "    List<Issue> findByName(String name);\n}\n",
            ),
        )

        sites = _calls(
            tmp_path,
            "    private IssueRepository issues;\n",
            "        issues.findByName(n);\n        issues.deleteOld();\n",
        )

        assert [(s.method, s.operation) for s in sites] == [
            ("findByName", OracleOperation.QUERY),
            ("deleteOld", OracleOperation.QUERY),
        ]

    def test_a_fragment_method_is_unknown_only_when_a_class_implements_it(
        self, tmp_path: Path
    ) -> None:
        # Spring Data routes a fragment interface's method to its `Impl` class.
        # With no implementation in the project it is a query method like any
        # other, and its name decides.
        _repositories(
            tmp_path,
            (
                "OrderRepository",
                "package com.acme.repo;\n\n" + _JPA + "\npublic interface OrderRepository "
                "extends JpaRepository<Order, String>, OrderCustom, OrderNamed {\n}\n",
            ),
            (
                "OrderCustom",
                "package com.acme.repo;\n\npublic interface OrderCustom {\n"
                "    List<Order> findStale();\n}\n",
            ),
            (
                "OrderCustomImpl",
                "package com.acme.repo;\n\npublic class OrderCustomImpl implements OrderCustom {\n"
                "    public List<Order> findStale() { return List.of(); }\n}\n",
            ),
            (
                "OrderNamed",
                "package com.acme.repo;\n\npublic interface OrderNamed {\n"
                "    List<Order> findByName(String name);\n}\n",
            ),
        )

        sites = _calls(
            tmp_path,
            "    private OrderRepository orders;\n",
            "        orders.findStale();\n        orders.findByName(n);\n",
        )

        assert [(s.method, s.operation) for s in sites] == [
            ("findStale", OracleOperation.UNKNOWN),
            ("findByName", OracleOperation.READ),
        ]

    def test_overloads_that_read_differently_are_unknown(self, tmp_path: Path) -> None:
        # The oracle does not match arity, so it does not pick between them.
        _repositories(
            tmp_path,
            (
                "OrderRepository",
                "package com.acme.repo;\n\n"
                "import org.springframework.data.jpa.repository.Query;\n" + _JPA + "\n"
                "public interface OrderRepository extends JpaRepository<Order, String> {\n"
                "    List<Order> findByStatus(String status);\n\n"
                '    @Query("select o from Order o where o.status = ?1 and o.vip = ?2")\n'
                "    List<Order> findByStatus(String status, boolean vip);\n}\n",
            ),
        )

        sites = _calls(
            tmp_path, "    private OrderRepository orders;\n", "        orders.findByStatus(s);\n"
        )

        assert [(s.method, s.operation) for s in sites] == [
            ("findByStatus", OracleOperation.UNKNOWN)
        ]


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
    # The hardening shapes (rigor review, export 2.15.0), one call per route at
    # 93 99 105 111 117 123 129 135 141 147 153 159.
    "web/HardeningController.java": 12,
    # `CrudRepository<Order, String>` field and parameter (review A2).
    "service/MarkerTypedOrders.java": 2,
    # `JpaRepository<E, String>`: a marker-typed receiver whose entity is unbound.
    "service/GenericStore.java": 1,
    # `R repository` where `R extends JpaRepository<Order, String>`.
    "service/BoundedStore.java": 1,
    # The pre-landing review's mixed statements: `findById` inside the HTTP
    # call's arguments at 29, and the `save` of an HTTP call's result at 35.
    # `restTemplate` is no repository, so each line is one site.
    "web/MixedSinkController.java": 2,
}


#: The oracle's operation reading of the same 86 sites, counted by hand from
#: each call's name and its repository declaration (review D6).
CRUD_MATRIX_OPERATIONS = {
    # 29, plus the hardening shapes: MarkerTypedOrders `count` and `existsById`,
    # GenericStore and BoundedStore `findAll`, Hardening 93 99 111 141
    # (`findTagged` reads by its name: the oracle matches declarations by name),
    # and MixedSinkController 29.
    OracleOperation.READ: 38,
    # Every save-family call, the default method's receiverless save included,
    # and MixedSinkController 35.
    OracleOperation.CREATE_OR_UPDATE: 18,
    # 47 59 82 83 84 of InheritedAndDerived, 128 of SaveController, and the
    # soft-deleted `Coupon` at Hardening 159 (the oracle does not read
    # `@SQLDelete`; wadi does, so this is an operation the two may differ on).
    OracleOperation.DELETE: 7,
    # `petRepository.insert` (golden 34).
    OracleOperation.CREATE: 1,
    # `orderRepository.flush()` (92).
    OracleOperation.NONE: 1,
    # Every `@Query` / `@Modifying` method QueryController calls: 54 60 66 72
    # 78 79 89 90 93 102 108; and Hardening 105 (the sub-interface's `@Query`
    # redeclaration), 135 (`@NativeQuery`), 153 (`audit.orders`).
    OracleOperation.QUERY: 14,
    # `sumOpen` (a name outside the table, golden 12), the `findAndTouch`
    # default method, and the `archiveOld` fragment `OrderRepositoryImpl`
    # implements. Hardening 117 (`@Update`), 123 (`@Procedure`), 129
    # (`@Aggregation`), and 147 `openOrders`: its project annotation is neutral
    # to the oracle and the name is outside the prefix table.
    OracleOperation.UNKNOWN: 7,
}

#: The entity of each of the 86 sites, from the repositories' type arguments.
CRUD_MATRIX_ENTITIES = {
    # 54, plus MarkerTypedOrders 2, BoundedStore 1, Hardening 123 135 141 147,
    # and MixedSinkController 29 and 35.
    "Order": 63,
    # ShapeController 60 61 (findAllByIdIn, declared by BaseRepository<E>) and
    # QueryController 90.
    "Issue": 3,
    # 2, plus Hardening 117 and 129.
    "Pet": 4,
    "Invoice": 2,
    # One billing and one crm `Account`: the simple name is the comparison.
    "Account": 2,
    "AuditEntry": 1,
    "OrderLine": 1,
    "Customer": 1,
    # Through `KeyedRepository<ID, E> extends JpaRepository<E, ID>`.
    "Ticket": 1,
    # AbstractArchiver's `BaseRepository<E>`: E is the class's type variable;
    # and GenericStore's `JpaRepository<E, String>`.
    None: 2,
    # `TripRepository extends KeyedJpaRepository<TripId, Trip>`, bound by
    # position, not by the first argument (review A4).
    "Trip": 1,
    "PetLog": 1,
    # Hardening 105 and 111.
    "Note": 2,
    "AuditedOrder": 1,
    "Coupon": 1,
}


class TestCrudMatrixFixture:
    def test_entity_and_operation_per_site_match_the_hand_count(self) -> None:
        sites = scan(CRUD_MATRIX).sites

        assert dict(Counter(site.operation for site in sites)) == CRUD_MATRIX_OPERATIONS
        assert dict(Counter(site.entity for site in sites)) == CRUD_MATRIX_ENTITIES

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
            "sites": 86,
            "in_lambda": 1,
            "method_references": 0,
            "by_module": {".": 86},
            "entity_unbound": 2,
            "by_operation": {
                "create": 1,
                "create-or-update": 18,
                "delete": 7,
                "none": 1,
                "query": 14,
                "read": 38,
                "unknown": 7,
            },
        }
        printed = capsys.readouterr().out
        assert "src/main/java/com/acme/crud/web/SaveController.java:144" in printed
        assert "sites: 86" in printed

    def test_a_run_stored_before_entity_and_operation_loads_with_neither(
        self, tmp_path: Path
    ) -> None:
        # Format 1 runs (the R1 train-ticket evidence) carry no reading; the
        # reconciler then says the oracle did not read them, never "agree".
        stored = tmp_path / "format-1.json"
        row = {
            "module": ".",
            "file": "src/main/java/A.java",
            "line": 3,
            "repository": "OrderRepository",
            "receiver": "orders",
            "method": "save",
            "enclosing_class": "A",
            "enclosing_method": "m",
            "in_lambda": False,
        }
        stored.write_text(json.dumps({"oracle_format": "1", "sites": [row]}))

        [site] = load_sites(stored)

        assert (site.method, site.entity, site.operation) == ("save", None, None)

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
