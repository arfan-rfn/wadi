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
    callers: List[String] = Nil
  ) {
    def json: ujson.Value = ujson.Obj(
      "argument_origin"        -> origin,
      "lookup_same_repository" -> lookup,
      "guard_arm"              -> arm,
      "caller_origins"         -> ujson.Arr.from(callers.map(ujson.Str(_)))
    )
  }

  /** One site's expected `db` raw facts. `save` is null on every row whose
    * method is not save-family, and that null is asserted too.
    */
  private case class Db(
    repository: String,
    method: String,
    entityText: Option[String],
    entityFullName: Option[String],
    kind: String = "jpa",
    implemented: Boolean = false,
    query: Option[Q] = None,
    save: Option[Save] = None
  ) {
    def json: ujson.Value = ujson.Obj(
      "repository"             -> repository,
      "method_name"            -> method,
      "entity_type_text"       -> entityText.map(ujson.Str(_)).getOrElse(ujson.Null),
      "entity_type_full_name"  -> entityFullName.map(ujson.Str(_)).getOrElse(ujson.Null),
      "repository_kind"        -> kind,
      "implemented_in_project" -> implemented,
      "query"                  -> query.map(_.json).getOrElse(ujson.Null),
      "save"                   -> save.map(_.json).getOrElse(ujson.Null)
    )
  }

  private def order(method: String, query: Option[Q] = None, implemented: Boolean = false): Db =
    Db(Repo + "OrderRepository", method, Some("Order"), Some(Dom + "Order"), implemented = implemented, query = query)

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
    "save-guard-not-found-arm" -> List(order("existsById"), orderSave(Save("constructed", lookup = true, "not-found"))),
    "save-guard-found-arm"     -> List(order("existsById"), orderSave(Save("constructed", lookup = true, "found"))),
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
        query = Some(Q(Some("select l from OrderLine l where l.sku = ?1")))
      )
    ),
    "query-jpql-update-modifying" -> List(
      order("updateStatus", Some(Q(Some("update Order o set o.status = ?2 where o.id = ?1"), modifying = true)))
    ),
    "query-jpql-join-association" -> List(
      order("findContainingSku", Some(Q(Some("select o from Order o join o.lines l where l.sku = ?1"))))
    ),
    "query-jpql-keyword-entity" -> List(
      order("findInStatus", Some(Q(Some("select o from Order o where o.status = ?1"))))
    ),
    "query-native-table" -> List(
      order("findNativeByStatus", Some(Q(Some("select * from orders where status = ?1"), native = true))),
      order(
        "findNativeConcatenated",
        Some(Q(Some("select * from orders where status = ?1 and id = ?2"), native = true))
      )
    ),
    "query-named" -> List(
      order(
        "shipped",
        Some(Q(Some("select o from Order o where o.status = 'SHIPPED'"), namedRef = Some("Order.findShipped")))
      ),
      // Through a @NamedQueries container, on a base-interface repository.
      Db(
        Repo + "IssueRepository",
        "findOpen",
        Some("Issue"),
        Some(Dom + "Issue"),
        query = Some(Q(Some("select i from Issue i where i.closed = false"), namedRef = Some("Issue.findOpen")))
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
      order("undeclaredNamed", Some(Q(None, namedRef = Some("Order.notDeclaredAnywhere"))))
    ),
    "query-mongo-json" -> List(
      Db(
        Repo + "PetRepository",
        "findByStatusJson",
        Some("Pet"),
        Some(Dom + "Pet"),
        kind = "mongo",
        query = Some(Q(Some("{ 'status': ?0 }")))
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
        )
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
    served.sorted shouldBe planGoldens.sorted
    goldens.keySet shouldBe planGoldens.toSet
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
    // OrderWriter, one in golden 32's default method, four in golden 34.
    saves.distinctBy(_("call_id").num.toLong) should have size 18
    dbRows.foreach { row =>
      val db = row("db")
      db.obj.contains("save") shouldBe true
      if (!saveFamily.contains(db("method_name").str)) db("save") shouldBe ujson.Null
      else {
        val save = db("save")
        save.obj.keySet shouldBe Set("argument_origin", "lookup_same_repository", "guard_arm", "caller_origins")
        origins should contain(save("argument_origin").str)
        Set("found", "not-found", "none") should contain(save("guard_arm").str)
        save("caller_origins").arr.foreach(o => origins should contain(o.str))
        // One hop is traced only for a parameter.
        if (save("argument_origin").str != "parameter") save("caller_origins").arr shouldBe empty
        // An arm is read only off a same-repository check, which is a lookup.
        if (save("guard_arm").str != "none") save("lookup_same_repository").bool shouldBe true
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
      "com.acme.crud.crm.Account"
    )
    exportJson("data_models").arr should have size 11
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
