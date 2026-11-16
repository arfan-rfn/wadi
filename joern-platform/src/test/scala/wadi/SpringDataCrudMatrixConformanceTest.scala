package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** Conformance test (P8) for Phase 2.10's entity-access raw facts (§5.2.17).
  *
  * `fixtures/spring-data-crud-matrix` has one controller method per golden in
  * the plan's "Fixture goldens, by name" list, served at `/crud/<golden>`. Each
  * golden pins its detected-site count and the `db` raw facts of every site.
  *
  * A golden's sites are the `kind=db` sink rows, one per distinct `call_id`,
  * in the methods its handler reaches through exported call edges. That is the
  * flow the worker builds the endpoint's ICFG from, so a site the count misses
  * is one the endpoint would never show.
  *
  * The export lands on a fixed path for the Python cross-language golden.
  */
class SpringDataCrudMatrixConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private lazy val exportJson: ujson.Value =
    exportFixture("spring-data-crud-matrix", "spring-data-crud-matrix-export")

  private lazy val cfgsByMethod: Map[Long, ujson.Value] =
    exportJson("cfgs").arr.map(c => c("method_id").num.toLong -> c).toMap

  private lazy val dbRows: Seq[ujson.Value] =
    exportJson("sinks").arr.toSeq.filter(_("kind").str == "db")

  private def handlerId(golden: String): Long =
    exportJson("endpoints").arr
      .find(_("uri").str == s"/crud/$golden")
      .map(_("method_id").num.toLong)
      .getOrElse(fail(s"no endpoint serves /crud/$golden"))

  /** Methods the handler reaches through exported call edges, itself included. */
  private def flowOf(root: Long): Set[Long] = {
    val seen  = scala.collection.mutable.Set(root)
    val queue = scala.collection.mutable.Queue(root)
    while (queue.nonEmpty) {
      val current = queue.dequeue()
      cfgsByMethod.get(current).toList.flatMap(_("nodes").arr).foreach { node =>
        node.obj.get("call").flatMap(_.obj.get("callee_id")).flatMap(_.numOpt).map(_.toLong).foreach { callee =>
          if (seen.add(callee)) queue.enqueue(callee)
        }
      }
    }
    seen.toSet
  }

  /** One row per distinct call site in the golden's flow. */
  private def sitesOf(golden: String): Seq[ujson.Value] = {
    val flow = flowOf(handlerId(golden))
    dbRows.filter(row => flow.contains(row("method_id").num.toLong)).distinctBy(_("call_id").num.toLong)
  }

  private val Repo = "com.acme.crud.repo."
  private val Dom  = "com.acme.crud.domain."

  // Annotations as `method_annotations` writes them: qualified (export 2.15.0).
  private val JpaQuery     = "org.springframework.data.jpa.repository.Query"
  private val JpaModifying = "org.springframework.data.jpa.repository.Modifying"
  private val MongoQuery   = "org.springframework.data.mongodb.repository.Query"

  // Spring Data's own interfaces, as a receiver declared by one names them.
  private val CrudRepositoryMarker = "org.springframework.data.repository.CrudRepository"
  private val JpaRepositoryMarker  = "org.springframework.data.jpa.repository.JpaRepository"

  /** A `query` object as the export writes it (A1). */
  private case class Q(
    text: Option[String],
    native: Boolean = false,
    namedRef: Option[String] = None,
    modifying: Boolean = false
  ) {
    def json: ujson.Value = ujson.Obj(
      "text"      -> text.map(ujson.Str(_)).getOrElse(ujson.Null),
      "native"    -> native,
      "named_ref" -> namedRef.map(ujson.Str(_)).getOrElse(ujson.Null),
      "modifying" -> modifying
    )
  }

  /** A `save` object as the export writes it (A1): rule 3's raw inputs.
    * Callers are in source order of their call sites.
    */
  private case class Save(
    origin: String,
    lookup: Boolean,
    arm: String = "none",
    callers: List[String] = Nil,
    guardLookup: Option[String] = None
  ) {
    def json: ujson.Value = ujson.Obj(
      "argument_origin"        -> origin,
      "lookup_same_repository" -> lookup,
      "guard_arm"              -> arm,
      "guard_lookup_method"    -> guardLookup.map(ujson.Str(_)).getOrElse(ujson.Null),
      "caller_origins"         -> ujson.Arr.from(callers.map(ujson.Str(_)))
    )
  }

  /** One site's expected `db` raw facts. `save` is null on every row whose
    * method is not save-family, and that null is asserted too. `annotations`
    * are the resolved declaration's, in source order (export 2.15.0).
    */
  private case class Db(
    repository: String,
    method: String,
    entityText: Option[String],
    entityFullName: Option[String],
    kind: String = "jpa",
    implemented: Boolean = false,
    query: Option[Q] = None,
    save: Option[Save] = None,
    annotations: List[String] = Nil,
    declarationResolved: Boolean = true
  ) {
    def json: ujson.Value = ujson.Obj(
      "repository"             -> repository,
      "method_name"            -> method,
      "entity_type_text"       -> entityText.map(ujson.Str(_)).getOrElse(ujson.Null),
      "entity_type_full_name"  -> entityFullName.map(ujson.Str(_)).getOrElse(ujson.Null),
      "repository_kind"        -> kind,
      "implemented_in_project" -> implemented,
      "query"                  -> query.map(_.json).getOrElse(ujson.Null),
      "save"                   -> save.map(_.json).getOrElse(ujson.Null),
      "method_annotations"     -> ujson.Arr.from(annotations.map(ujson.Str(_))),
      "declaration_resolved"   -> declarationResolved
    )
  }

  private def order(
    method: String,
    query: Option[Q] = None,
    implemented: Boolean = false,
    annotations: List[String] = Nil
  ): Db =
    Db(
      Repo + "OrderRepository",
      method,
      Some("Order"),
      Some(Dom + "Order"),
      implemented = implemented,
      query = query,
      annotations = annotations
    )

  /** An OrderRepository save-family site with its `save` facts. */
  private def orderSave(save: Save, method: String = "save"): Db = order(method).copy(save = Some(save))

  /** The plan's "Fixture goldens, by name" list (R1-18), in its numbering. */
  private val planGoldens: List[String] = List(
    "inherited-find-by-id",
    "inherited-save-read-origin",
    "inherited-delete",
    "derived-find-by-status",
    "derived-delete-by",
    "derived-count-exists",
    "query-jpql-select",
    "query-jpql-update-modifying",
    "query-jpql-join-association",
    "query-jpql-keyword-entity",
    "query-native-table",
    "query-named",
    "query-mongo-json",
    "base-interface-repository",
    "save-constructed-no-lookup",
    "save-guard-not-found-arm",
    "save-guard-found-arm",
    "save-guard-early-return",
    "save-upsert-by-branch",
    "save-parameter-callers-agree",
    "save-parameter-callers-disagree",
    "save-parameter-from-request-body",
    "save-via-helper-wrapper",
    "delete-then-save",
    "two-calls-one-statement",
    "save-in-lambda",
    "dirty-checking-setter",
    "forwarding-endpoint",
    "repository-only-entity",
    "unbindable-entity-chain",
    "query-delete-with-subquery",
    "repository-default-method",
    "repository-custom-fragment",
    "inherited-method-table",
    "flush-not-an-operation",
    "same-simple-name-two-packages"
  )

  /** Golden name → the raw facts of every site in its flow, in any order. */
  private val goldens: Map[String, List[Db]] = Map(
    "inherited-find-by-id" -> List(order("findById")),
    "inherited-delete"     -> List(order("deleteById")),
    "derived-find-by-status" -> List(order("findByStatus")),
    "derived-delete-by"      -> List(order("deleteByStatus")),
    "derived-count-exists"   -> List(order("countByStatus"), order("existsByStatus")),
    // R1-4: both calls bind E through BaseRepository<E> by position, from the
    // RECEIVER's type; the base-declared method names IssueRepository too.
    // KeyedRepository<ID, E> extends JpaRepository<E, ID>: by name the first
    // argument would read String.
    "base-interface-repository" -> List(
      Db(Repo + "IssueRepository", "findById", Some("Issue"), Some(Dom + "Issue")),
      Db(Repo + "IssueRepository", "findAllByIdIn", Some("Issue"), Some(Dom + "Issue")),
      Db(Repo + "TicketRepository", "findById", Some("Ticket"), Some(Dom + "Ticket"))
    ),
    "repository-only-entity" -> List(
      Db(Repo + "AuditEntryRepository", "findAll", Some("AuditEntry"), Some(Dom + "AuditEntry"), kind = "other")
    ),
    // The receiver is BaseRepository<E> itself: nothing binds E (P10).
    "unbindable-entity-chain" -> List(Db(Repo + "BaseRepository", "count", None, None)),
    // Save shapes (rule 3): each pins the RAW facts, never a verb (the worker
    // classifies, Q22/Q23). Origin is def-use inside the saving method.
    "inherited-save-read-origin" -> List(order("findById"), orderSave(Save("read", lookup = true))),
    "save-constructed-no-lookup" -> List(orderSave(Save("constructed", lookup = false))),
    // Q23: the save sits directly in an arm of the same-repository check.
    "save-guard-not-found-arm" -> List(
      order("existsById"),
      orderSave(Save("constructed", lookup = true, "not-found", guardLookup = Some("existsById")))
    ),
    "save-guard-found-arm" -> List(
      order("existsById"),
      orderSave(Save("constructed", lookup = true, "found", guardLookup = Some("existsById")))
    ),
    // The check returns early; the save follows it and is in no arm.
    "save-guard-early-return" -> List(order("existsById"), orderSave(Save("constructed", lookup = true))),
    // `new` on one branch, a read on the other: both definitions reach the save.
    "save-upsert-by-branch" -> List(order("findById"), orderSave(Save("mixed", lookup = true))),
    // Two reads in the handler, ONE save site in OrderWriter.storeAgreed that
    // both calls reach: a site is a call site, not a call. Its origin is a
    // parameter; each caller's argument is a read (R1-27, one hop).
    "save-parameter-callers-agree" -> List(
      order("findById"),
      order("findById"),
      orderSave(Save("parameter", lookup = false, callers = List("read", "read")))
    ),
    "save-parameter-callers-disagree" -> List(
      order("findById"),
      orderSave(Save("parameter", lookup = false, callers = List("read", "constructed")))
    ),
    // The caller passes its own @RequestBody: still a parameter after one hop.
    "save-parameter-from-request-body" -> List(
      orderSave(Save("parameter", lookup = false, callers = List("parameter")))
    ),
    // The read is in OrderLookup.loadEnvelope, one call away; here the object
    // comes out of a wrapper's getter, which def-use does not follow.
    "save-via-helper-wrapper" -> List(order("findById"), orderSave(Save("other", lookup = false))),
    // A delete is not a lookup. The rebuilt object comes from a static
    // factory on the entity type, which constructs.
    "delete-then-save" -> List(order("deleteById"), orderSave(Save("constructed", lookup = false))),
    // The saved argument IS the findById call.
    "two-calls-one-statement" -> List(orderSave(Save("read", lookup = true)), order("findById")),
    // The lambda body is in the export but in no endpoint flow (R1-1): see
    // the dedicated test below.
    "save-in-lambda" -> Nil,
    // Q2: the setter is the update; the read is the only site.
    "dirty-checking-setter" -> List(order("findById")),
    // Q26: forwards, touches nothing locally.
    "forwarding-endpoint" -> Nil,
    // E5: the inherited CrudRepository / JpaRepository / MongoRepository
    // surface, one site each.
    "inherited-method-table" -> List(
      order("findAll"),
      order("findAllById"),
      order("count"),
      order("existsById"),
      order("getReferenceById"),
      // Each saved list or object was read from the same repository above.
      orderSave(Save("read", lookup = true), "saveAll"),
      orderSave(Save("read", lookup = true), "saveAndFlush"),
      orderSave(Save("read", lookup = true), "saveAllAndFlush"),
      order("deleteAllById"),
      order("deleteAllInBatch"),
      order("deleteAll"),
      // A builder rooted at the entity type constructs; nothing reads from
      // PetRepository in this method.
      Db(
        Repo + "PetRepository",
        "insert",
        Some("Pet"),
        Some(Dom + "Pet"),
        kind = "mongo",
        save = Some(Save("constructed", lookup = false))
      )
    ),
    "flush-not-an-operation" -> List(order("flush")),
    // R1-12: a query method's name never decides its verb, so the text and
    // its flags travel with the site for the reader (M6).
    "query-jpql-select" -> List(
      Db(
        Repo + "OrderLineRepository",
        "findBySkuText",
        Some("OrderLine"),
        Some(Dom + "OrderLine"),
        query = Some(Q(Some("select l from OrderLine l where l.sku = ?1"))),
        annotations = List(JpaQuery)
      )
    ),
    "query-jpql-update-modifying" -> List(
      order(
        "updateStatus",
        Some(Q(Some("update Order o set o.status = ?2 where o.id = ?1"), modifying = true)),
        annotations = List(JpaModifying, JpaQuery)
      )
    ),
    "query-jpql-join-association" -> List(
      order(
        "findContainingSku",
        Some(Q(Some("select o from Order o join o.lines l where l.sku = ?1"))),
        annotations = List(JpaQuery)
      )
    ),
    "query-jpql-keyword-entity" -> List(
      order("findInStatus", Some(Q(Some("select o from Order o where o.status = ?1"))), annotations = List(JpaQuery))
    ),
    "query-native-table" -> List(
      order(
        "findNativeByStatus",
        Some(Q(Some("select * from orders where status = ?1"), native = true)),
        annotations = List(JpaQuery)
      ),
      order(
        "findNativeConcatenated",
        Some(Q(Some("select * from orders where status = ?1 and id = ?2"), native = true)),
        annotations = List(JpaQuery)
      )
    ),
    "query-named" -> List(
      order(
        "shipped",
        Some(Q(Some("select o from Order o where o.status = 'SHIPPED'"), namedRef = Some("Order.findShipped"))),
        annotations = List(JpaQuery)
      ),
      // Through a @NamedQueries container, on a base-interface repository.
      Db(
        Repo + "IssueRepository",
        "findOpen",
        Some("Issue"),
        Some(Dom + "Issue"),
        query = Some(Q(Some("select i from Issue i where i.closed = false"), namedRef = Some("Issue.findOpen"))),
        annotations = List(JpaQuery)
      ),
      // Implicit key `<entity name>.<method>`: the JPQL name, not the class.
      Db(
        Repo + "CustomerRepository",
        "findVip",
        Some("Customer"),
        Some(Dom + "Customer"),
        query = Some(Q(Some("select c from Client c where c.vip = true"), namedRef = Some("Client.findVip")))
      ),
      Db(
        Repo + "InvoiceRepository",
        "sumOpen",
        Some("Invoice"),
        Some(Dom + "Invoice"),
        query = Some(
          Q(Some("select sum(amount) from invoices where paid = false"), native = true, namedRef = Some("Invoice.sumOpen"))
        )
      ),
      // A name nothing declares keeps the name and no text (P10).
      order("undeclaredNamed", Some(Q(None, namedRef = Some("Order.notDeclaredAnywhere"))), annotations = List(JpaQuery))
    ),
    "query-mongo-json" -> List(
      Db(
        Repo + "PetRepository",
        "findByStatusJson",
        Some("Pet"),
        Some(Dom + "Pet"),
        kind = "mongo",
        query = Some(Q(Some("{ 'status': ?0 }"))),
        annotations = List(MongoQuery)
      )
    ),
    // C1's shape: one site; the text names Invoice and Client.
    "query-delete-with-subquery" -> List(
      Db(
        Repo + "InvoiceRepository",
        "deleteForNonVip",
        Some("Invoice"),
        Some(Dom + "Invoice"),
        query = Some(
          Q(Some("delete from Invoice i where i.customer in (select c from Client c where c.vip = false)"), modifying = true)
        ),
        annotations = List(JpaModifying, JpaQuery)
      )
    ),
    // C3: a `default` body is in the project, so its name proves nothing. The
    // calls INSIDE it are ordinary inherited calls on `this`.
    "repository-default-method" -> List(
      order("findAndTouch", implemented = true),
      order("findById"),
      // The receiver is `this`; the lookup is the findById on it.
      orderSave(Save("read", lookup = true))
    ),
    // C3: the fragment's body is OrderRepositoryImpl.archiveOld.
    "repository-custom-fragment" -> List(order("archiveOld", implemented = true)),
    // C2: one simple name, two types, told apart by the file each is named in.
    "same-simple-name-two-packages" -> List(
      Db("com.acme.crud.billing.AccountRepository", "findById", Some("Account"), Some("com.acme.crud.billing.Account")),
      Db(Repo + "CrmAccountRepository", "findById", Some("Account"), Some("com.acme.crud.crm.Account"))
    )
  )

  /** The shapes the rigor review found misread or uncounted (§5.2.17,
    * "Hardening after the rigor review"), one handler each in
    * `HardeningController`. Served at `/crud/<shape>` like the plan's.
    */
  private val hardeningGoldens: List[String] = List(
    "marker-typed-receiver",
    "marker-receiver-unbound-entity",
    "type-variable-receiver",
    "marker-named-project-base",
    "marker-named-mongo-base",
    "redeclared-query-override",
    "arity-mismatch",
    "annotation-mongo-update",
    "annotation-procedure",
    "annotation-aggregation",
    "annotation-native-query",
    "annotation-neutral",
    "annotation-project-meta-query",
    "query-native-schema-table",
    "soft-delete-entity"
  )

  private val hardening: Map[String, List[Db]] = Map(
    // Review A2: receivers declared as Spring Data's own interface, a field
    // and a parameter. Each is a repository call; the entity is the declared
    // type argument, resolved through the declaring file's imports.
    "marker-typed-receiver" -> List(
      Db(CrudRepositoryMarker, "count", Some("Order"), Some(Dom + "Order"), kind = "other"),
      Db(CrudRepositoryMarker, "existsById", Some("Order"), Some(Dom + "Order"), kind = "other")
    ),
    // The declared argument is the class's own `E`: kept as written, unbound.
    "marker-receiver-unbound-entity" -> List(Db(JpaRepositoryMarker, "findAll", Some("E"), None)),
    // `R extends JpaRepository<Order, String>`: the bound is the repository.
    "type-variable-receiver" -> List(Db(JpaRepositoryMarker, "findAll", Some("Order"), Some(Dom + "Order"))),
    // Review A4: a project base whose name contains a marker's is not one.
    // `KeyedJpaRepository<TripId, Trip>` binds Trip by position; by the old
    // substring rule it was the marker and its first argument, TripId, won.
    "marker-named-project-base" -> List(Db(Repo + "TripRepository", "findById", Some("Trip"), Some(Dom + "Trip"))),
    // `BaseCrudRepository<E> extends MongoRepository<E, String>`: the kind is
    // the marker's, mongo, not the project name's.
    "marker-named-mongo-base" -> List(
      Db(Repo + "PetLogRepository", "findAll", Some("PetLog"), Some(Dom + "PetLog"), kind = "mongo")
    ),
    // Review A3: the sub-interface redeclares the base method with @Query,
    // and that nearest declaration is the one read.
    "redeclared-query-override" -> List(
      Db(
        Repo + "NoteRepository",
        "search",
        Some("Note"),
        Some(Dom + "Note"),
        query = Some(Q(Some("select n from Note n where n.body like ?1"))),
        annotations = List(JpaQuery, "java.lang.Override")
      )
    ),
    // Two arguments, and the chain declares `findTagged` only with one
    // (varargs): no declaration is chosen, and none is read.
    "arity-mismatch" -> List(
      Db(Repo + "NoteRepository", "findTagged", Some("Note"), Some(Dom + "Note"), declarationResolved = false)
    ),
    // Review B1: annotations the worker reads to withhold a name's verb.
    "annotation-mongo-update" -> List(
      Db(
        Repo + "PetRepository",
        "findAndIncrementVisitsByStatus",
        Some("Pet"),
        Some(Dom + "Pet"),
        kind = "mongo",
        annotations = List("org.springframework.data.mongodb.repository.Update")
      )
    ),
    "annotation-procedure" -> List(
      order("getArchivedCount", annotations = List("org.springframework.data.jpa.repository.query.Procedure"))
    ),
    "annotation-aggregation" -> List(
      Db(
        Repo + "PetRepository",
        "findStatusSummary",
        Some("Pet"),
        Some(Dom + "Pet"),
        kind = "mongo",
        annotations = List("org.springframework.data.mongodb.repository.Aggregation")
      )
    ),
    // `@NativeQuery` reads exactly as `@Query(nativeQuery = true)`.
    "annotation-native-query" -> List(
      order(
        "findNativeAnnotated",
        Some(Q(Some("select * from orders where status = ?1"), native = true)),
        annotations = List("org.springframework.data.jpa.repository.NativeQuery")
      )
    ),
    "annotation-neutral" -> List(
      order(
        "findFirstByStatus",
        annotations = List(
          "org.springframework.transaction.annotation.Transactional",
          "org.springframework.data.jpa.repository.Lock"
        )
      )
    ),
    // A project annotation's own annotations follow it, one level, as
    // `<annotation>><meta-annotation>`. The export reads no query from them.
    "annotation-project-meta-query" -> List(
      order(
        "openOrders",
        annotations = List(
          Repo + "OpenOrdersQuery",
          Repo + "OpenOrdersQuery>java.lang.annotation.Target",
          Repo + "OpenOrdersQuery>java.lang.annotation.Retention",
          Repo + "OpenOrdersQuery>" + JpaQuery
        )
      )
    ),
    // Review B2: the text keeps its schema; `storage_schema` says which
    // entity declares it (asserted with the data models below).
    "query-native-schema-table" -> List(
      Db(
        Repo + "AuditedOrderRepository",
        "findAuditedByStatus",
        Some("AuditedOrder"),
        Some(Dom + "AuditedOrder"),
        query = Some(Q(Some("select * from audit.orders where status = ?1"), native = true)),
        annotations = List(JpaQuery)
      )
    ),
    // Review B1: an ordinary inherited delete; `delete_rewritten_by` on the
    // entity's record is what says it deletes no row.
    "soft-delete-entity" -> List(Db(Repo + "CouponRepository", "deleteById", Some("Coupon"), Some(Dom + "Coupon")))
  )

  hardeningGoldens.foreach { golden =>
    val expected = hardening.getOrElse(golden, Nil)
    test(s"hardening $golden: ${expected.size} site(s) with their db raw facts") {
      hardening.contains(golden) shouldBe true
      sitesOf(golden).map(factsOf).map(_.render()).sorted shouldBe expected.map(_.json.render()).sorted
    }
  }

  /** One statement that makes a repository call and an HTTP call, nested each
    * way (§5.2.17, "Found by the pre-landing review" #1 and #2), one handler
    * each in `MixedSinkController`. Goldens 52 and 53 in the Python numbering.
    */
  private val preLandingGoldens: List[String] = List("http-wraps-repository", "repository-wraps-http")

  private val preLanding: Map[String, List[Db]] = Map(
    // The read is the HTTP call's argument, and a site of its own.
    "http-wraps-repository" -> List(order("findById")),
    // The saved object is what the HTTP call returned. Def-use does not
    // follow a call's result into the callee, as with golden 23's getter.
    "repository-wraps-http" -> List(orderSave(Save("other", lookup = false)))
  )

  preLandingGoldens.foreach { golden =>
    val expected = preLanding.getOrElse(golden, Nil)
    test(s"pre-landing $golden: ${expected.size} site(s) with their db raw facts") {
      preLanding.contains(golden) shouldBe true
      sitesOf(golden).map(factsOf).map(_.render()).sorted shouldBe expected.map(_.json.render()).sorted
    }
  }

  /** Every sink row of the handler's own statements, in export order. */
  private def handlerSinkRows(golden: String): Seq[ujson.Value] = {
    val handler = handlerId(golden)
    exportJson("sinks").arr.toSeq.filter(_("method_id").num.toLong == handler)
  }

  /** A row as `(kind, what it names)`: the repository method, or verb and URL. */
  private def described(row: ujson.Value): (String, String) =
    row("kind").str match {
      case "db" => ("db", row("db")("method_name").str)
      case kind => (kind, s"${row("http_verb").str} ${row("value").str}")
    }

  /** The method name of the call the export chose as the node's primary. */
  private def primaryCallOf(golden: String, nodeId: Long): String = {
    val node = cfgsByMethod(handlerId(golden))("nodes").arr.find(_("id").num.toLong == nodeId).get
    node("call")("callee_full_name").str.split(':').head.split('.').last
  }

  test("golden 52 http-wraps-repository: the HTTP call is primary and the read inside it keeps its db row (pre-landing #1)") {
    val rows = handlerSinkRows("http-wraps-repository")
    // The primary call's rows come first: the worker takes the node's kind
    // from them, and reads every other row by its own kind.
    rows.map(described) shouldBe List(
      ("http-client", "POST http://ts-order-service:12346/api/v1/orders"),
      ("db", "findById")
    )
    rows.map(_("node_id").num.toLong).distinct should have size 1
    rows.map(_("call_id").num.toLong).distinct should have size 2
    primaryCallOf("http-wraps-repository", rows.head("node_id").num.toLong) shouldBe "postForObject"
  }

  test("golden 53 repository-wraps-http: the save is primary and the HTTP call inside it gets its row (pre-landing #2)") {
    val rows = handlerSinkRows("repository-wraps-http")
    rows.map(described) shouldBe List(
      ("db", "save"),
      ("http-client", "GET http://ts-order-service:12346/api/v1/orders/{?}")
    )
    rows.map(_("node_id").num.toLong).distinct should have size 1
    rows.map(_("call_id").num.toLong).distinct should have size 2
    primaryCallOf("repository-wraps-http", rows.head("node_id").num.toLong) shouldBe "save"
  }

  /** A site's whole `db` object, `save` included; facts compare order-free. */
  private def factsOf(site: ujson.Value): ujson.Value =
    site.obj.getOrElse("db", fail(s"db sink row without a db object: $site"))

  planGoldens.zipWithIndex.foreach { case (golden, index) =>
    val expected = goldens.getOrElse(golden, Nil)
    test(f"golden ${index + 1}%02d $golden: ${expected.size} site(s) with their db raw facts") {
      goldens.contains(golden) shouldBe true
      val sites = sitesOf(golden)
      // `save` is compared with the rest: its facts on a save-family row, an
      // explicit null on every other row.
      sites.map(factsOf).map(_.render()).sorted shouldBe expected.map(_.json.render()).sorted
    }
  }

  test("every golden in the plan's list has exactly one handler and one table entry (R1-18)") {
    val served = exportJson("endpoints").arr.map(_("uri").str).filter(_.startsWith("/crud/")).map(_.stripPrefix("/crud/"))
    planGoldens should have size 36
    // The plan's 36, the hardening shapes and the pre-landing ones, and
    // nothing else.
    served.sorted shouldBe (planGoldens ++ hardeningGoldens ++ preLandingGoldens).sorted
    goldens.keySet shouldBe planGoldens.toSet
    hardening.keySet shouldBe hardeningGoldens.toSet
    preLanding.keySet shouldBe preLandingGoldens.toSet
  }

  test("golden 26 save-in-lambda: the lambda's save is a db row outside the endpoint's flow (R1-1)") {
    val handler = exportJson("methods").arr.find(_("id").num.toLong == handlerId("save-in-lambda")).get
    val lambdas = exportJson("methods").arr.filter { m =>
      m("full_name").str.contains("<lambda>") && m("filename").str == handler("filename").str &&
      m("line").num >= handler("line").num && m("line").num <= handler("line_end").num
    }
    val rows = dbRows.filter(row => lambdas.exists(_("id").num.toLong == row("method_id").num.toLong))
    // Facts are per call site, so the row carries them even though no
    // endpoint ICFG reaches it.
    rows.map(factsOf).map(_.render()) shouldBe List(orderSave(Save("constructed", lookup = false)).json.render())
    flowOf(handlerId("save-in-lambda")).intersect(lambdas.map(_("id").num.toLong).toSet) shouldBe empty
  }

  test("golden 28 forwarding-endpoint: one outbound http call and no repository call (Q26)") {
    val flow = flowOf(handlerId("forwarding-endpoint"))
    val http = exportJson("sinks").arr.filter(r => r("kind").str == "http-client" && flow.contains(r("method_id").num.toLong))
    http.map(_("value").str) shouldBe List("http://ts-station-service:12345/api/v1/stations/{?}")
  }

  test("every db sink row in the export carries a db object, and only db rows do") {
    exportJson("sinks").arr.foreach { row =>
      row.obj.contains("db") shouldBe (row("kind").str == "db")
    }
  }

  test("A1 save: every save-family row in the export has a save object in the contract's vocabulary; every other row null") {
    val saveFamily = Set("save", "saveAndFlush", "saveAll", "saveAllAndFlush", "insert")
    val origins    = Set("read", "constructed", "parameter", "mixed", "other")
    val saves = dbRows.filter(row => saveFamily.contains(row("db")("method_name").str))
    // Ten in SaveController (golden 26's lambda included), three in
    // OrderWriter, one in golden 32's default method, four in golden 34, and
    // golden 53's save of what an HTTP call returned.
    saves.distinctBy(_("call_id").num.toLong) should have size 19
    dbRows.foreach { row =>
      val db = row("db")
      db.obj.contains("save") shouldBe true
      if (!saveFamily.contains(db("method_name").str)) db("save") shouldBe ujson.Null
      else {
        val save = db("save")
        save.obj.keySet shouldBe
          Set("argument_origin", "lookup_same_repository", "guard_arm", "guard_lookup_method", "caller_origins")
        origins should contain(save("argument_origin").str)
        Set("found", "not-found", "none") should contain(save("guard_arm").str)
        save("caller_origins").arr.foreach(o => origins should contain(o.str))
        // One hop is traced only for a parameter.
        if (save("argument_origin").str != "parameter") save("caller_origins").arr shouldBe empty
        // An arm is read only off a same-repository check, which is a lookup.
        if (save("guard_arm").str != "none") save("lookup_same_repository").bool shouldBe true
        // The lookup a guard tests is named exactly when an arm is read.
        (save("guard_lookup_method") != ujson.Null) shouldBe (save("guard_arm").str != "none")
      }
    }
  }

  // --- entity records (A2) ---------------------------------------------------

  private lazy val models: Map[String, ujson.Value] =
    exportJson("data_models").arr.map(m => m("type_full_name").str -> m).toMap

  private def model(fullName: String): ujson.Value =
    models.getOrElse(fullName, fail(s"no data_models row for $fullName; saw ${models.keys.toList.sorted}"))

  private def field(fullName: String, name: String): ujson.Value =
    model(fullName)("fields").arr.find(_("name").str == name).getOrElse(fail(s"$fullName has no field $name"))

  test("data_models: one row per entity, keyed by qualified name, the repository-only one included (Q1, C2)") {
    models.keySet shouldBe Set(
      Dom + "Order",
      Dom + "Customer",
      Dom + "OrderLine",
      Dom + "Invoice",
      Dom + "Issue",
      Dom + "Ticket",
      Dom + "AuditEntry",
      Dom + "Pet",
      Dom + "Shipment",
      "com.acme.crud.billing.Account",
      "com.acme.crud.crm.Account",
      // The hardening shapes' entities. TripId is not one: it is the key
      // `KeyedJpaRepository<TripId, Trip>` binds second (review A4).
      Dom + "Trip",
      Dom + "PetLog",
      Dom + "Note",
      Dom + "AuditedOrder",
      Dom + "Coupon"
    )
    exportJson("data_models").arr should have size 16
  }

  test("data_models: how each entity was declared") {
    model(Dom + "Order")("declared_by").str shouldBe "annotation"
    model(Dom + "Pet")("declared_by").str shouldBe "annotation"
    // Q1: no @Entity and no @Document; only AuditEntryRepository names it.
    val audit = model(Dom + "AuditEntry")
    audit("declared_by").str shouldBe "repository-argument"
    audit("entity").str shouldBe "AuditEntry"
    audit("jpql_name") shouldBe ujson.Null
    audit("storage_name") shouldBe ujson.Null
    audit("fields").arr.map(_("name").str) should contain("message")
  }

  test("data_models: the JPQL name is @Entity(name=) when set, else absent") {
    model(Dom + "Customer")("jpql_name").str shouldBe "Client"
    model("com.acme.crud.billing.Account")("jpql_name").str shouldBe "BillingAccount"
    model(Dom + "Order")("jpql_name") shouldBe ujson.Null
    model("com.acme.crud.crm.Account")("jpql_name") shouldBe ujson.Null
  }

  test("data_models: the storage name from @Table and each @Document form (R1-3)") {
    model(Dom + "Order")("storage_name").str shouldBe "orders"
    model(Dom + "Customer")("storage_name").str shouldBe "customers"
    model(Dom + "Pet")("storage_name").str shouldBe "pets"
    model(Dom + "Shipment")("storage_name").str shouldBe "shipments"
    model(Dom + "OrderLine")("storage_name") shouldBe ujson.Null
  }

  test("data_models: the schema from @Table(schema=), null where none is declared (export 2.15.0, review B2)") {
    model(Dom + "AuditedOrder")("storage_name").str shouldBe "orders"
    model(Dom + "AuditedOrder")("storage_schema").str shouldBe "audit"
    model(Dom + "Order")("storage_schema") shouldBe ujson.Null
    exportJson("data_models").arr.count(_("storage_schema") != ujson.Null) shouldBe 1
  }

  test("data_models: a Hibernate @SQLDelete names what rewrites the delete (export 2.15.0, review B1)") {
    model(Dom + "Coupon")("delete_rewritten_by").str shouldBe "org.hibernate.annotations.SQLDelete"
    exportJson("data_models").arr.count(_("delete_rewritten_by") != ujson.Null) shouldBe 1
  }

  test("export 2.15.0: every new field is on every row, with its default where nothing was read") {
    exportJson("export_schema_version").str shouldBe "2.15.0"
    dbRows.foreach { row =>
      row("db")("method_annotations").arr.foreach(_.str)
      row("db")("declaration_resolved").bool
    }
    exportJson("data_models").arr.foreach { m =>
      m.obj.keySet should contain allOf ("storage_schema", "delete_rewritten_by")
    }
  }

  test("save_origin_rules: the build's hash of the save-fact sources, on the export (review B4)") {
    exportJson("save_origin_rules").str should fullyMatch regex "[0-9a-f]{16}"
  }

  test("data_models: a field's declared type keeps its generics; type_name stays erased (R1-3)") {
    field(Dom + "Order", "lines")("declared_type").str shouldBe "List<OrderLine>"
    field(Dom + "Order", "lines")("type_name").str shouldBe "java.util.List"
    field(Dom + "Order", "customer")("declared_type").str shouldBe "Customer"
    field(Dom + "Pet", "tags")("declared_type").str shouldBe "List<String>"
  }

  test("golden 25 two-calls-one-statement: one statement, two repository calls, two rows (R1-2)") {
    val sites = sitesOf("two-calls-one-statement")
    sites.map(_("node_id").num.toLong).distinct should have size 1
    sites.map(_("call_id").num.toLong).distinct should have size 2
  }
}
