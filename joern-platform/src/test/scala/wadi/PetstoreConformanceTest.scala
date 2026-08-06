package wadi

import org.scalatest.BeforeAndAfterAll
import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** Conformance test (P8): the whole in-graph pipeline against spring-petstore-mini.
  *
  * Proves the week-one validation targets (§11): DI resolution crosses the
  * interface boundary, endpoints/sinks/models are tagged with registry
  * vocabulary, and the bulk export lands on disk in the contract shape.
  */
class PetstoreConformanceTest extends AnyFunSuite with Matchers with BeforeAndAfterAll with FixtureCpg {

  // Fixed output path (gitignored): the Python side's cross-language test reads
  // this exact file to prove the export parses and assembles end to end.
  private lazy val exportJson: ujson.Value = exportFixture("spring-petstore-mini", "petstore-export")

  private def endpoints: Set[String] =
    exportJson("endpoints").arr.map(e => s"${e("http_method").str} ${e("uri").str}").toSet

  private def methodByFullName(fragment: String): Option[ujson.Value] =
    exportJson("methods").arr.find(_("full_name").str.contains(fragment))

  test("all three fixture endpoints are found with correct URIs") {
    endpoints should contain allOf ("GET /pets/{id}", "POST /pets", "GET /owners")
  }

  test("Feign client interfaces are NOT counted as endpoints") {
    // InventoryClient carries @GetMapping but declares an outbound call
    // (found the hard way against TrainTicket ground truth).
    endpoints should have size 3
    endpoints.exists(_.contains("/api/v1/inventory/stock")) shouldBe false
  }

  test("DI resolution pulls the ServiceImpl into the endpoint closure") {
    // Without SpringDIPass the closure stops at the PetService interface.
    methodByFullName("PetServiceImpl.findPet") should be(defined)
    methodByFullName("PetServiceImpl.createPet") should be(defined)
  }

  test("db sink is tagged on the repository call") {
    val sinks = exportJson("sinks").arr
    val dbSinks = sinks.filter(_("kind").str == "db")
    dbSinks should not be empty
  }

  test("http-client sink slices the field-held host into a HIGH-confidence URL") {
    // Phase 1 recovered only `{?}/stock/{?}` (the host lived in a field);
    // the §5.2.4 slicer resolves the single-assignment field and keeps the
    // path parameter as a benign `{?}` hole.
    val httpSinks = exportJson("sinks").arr.filter(_("kind").str == "http-client")
    httpSinks should not be empty
    val sink = httpSinks.head
    sink("value").str shouldBe "http://inventory:8080/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    sink("call_id").numOpt should not be empty
    sink("evidence").str should include("single assignment")
  }

  test("persisted model is exported with its fields") {
    val models = exportJson("data_models").arr
    models.map(_("entity").str) should contain("Pet")
    val pet = models.find(_("entity").str == "Pet").get
    pet("fields").arr.map(_("name").str) should contain allOf ("id", "name", "stockCount")
  }

  test("handler methods have coarsened CFGs with branch nodes and conditions") {
    val findPetMethod = methodByFullName("PetServiceImpl.findPet").get
    val methodId      = findPetMethod("id").num.toLong
    val cfg = exportJson("cfgs").arr.find(_("method_id").num.toLong == methodId).get
    val kinds = cfg("nodes").arr.map(_("kind").str).toSet
    kinds should contain("branch")
    kinds should contain("call")
    kinds should contain("return")
    val branch = cfg("nodes").arr.find(_("kind").str == "branch").get
    branch.obj.get("condition_code").map(_.str).getOrElse("") should not be empty
    // true/false labels present on branch edges
    cfg("edges").arr.map(_("label").str).toSet should contain("true")
  }

  test("export document declares the contract version") {
    exportJson("export_schema_version").str shouldBe "2.11.0"
  }

  test("analysis coverage counts production vs reachable methods (§5.4.3)") {
    val coverage = exportJson("analysis_coverage")
    // Denominator 9 = PetController(2) + OwnerController(1) + PetServiceImpl(2)
    // + Pet accessors(4). The 3 unreached are Pet's serialization-only getters
    // (getId/getName/getStockCount) — never called in code, exactly the honest
    // signal the metric exists to expose. Abstract interface methods
    // (PetService, PetRepository, InventoryClient) count on neither side, even
    // though PetService's stubs sit in the exported closure.
    coverage("production_methods").num.toInt shouldBe 9
    coverage("reachable_production_methods").num.toInt shouldBe 6
  }

  override def afterAll(): Unit = {
    // temp dirs cleaned by the OS; nothing persistent to remove
    super.afterAll()
  }
}
