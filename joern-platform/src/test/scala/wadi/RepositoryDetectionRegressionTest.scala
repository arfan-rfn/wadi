package wadi

import io.joern.javasrc2cpg.{Config, JavaSrc2Cpg}
import io.joern.x2cpg.X2Cpg
import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.semanticcpg.language.*
import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}
import scala.util.Using

import wadi.packs.SpringDataSinkPass

/** E7: repository detection became transitive (Q10), and that must not move
  * a single `sink=db` tag on a system without a base interface.
  *
  * Each fixture is tagged twice in one CPG: by the shipped pass, and by a
  * frozen copy of the pre-2.10 rule. Comparing call ids side by side is exact
  * (ids are only stable within one graph), and the recorded sizes pin the
  * before-sets so a change that moved both rules at once would still fail.
  */
class RepositoryDetectionRegressionTest extends AnyFunSuite with Matchers {

  /** The rule as it stood at export 2.12.0, verbatim: a type is a repository
    * when one of its DIRECT parents carries a marker, and a call is tagged
    * when the type named in its methodFullName is one.
    */
  private def preTransitiveDbCallIds(cpg: Cpg): Set[Long] = {
    val markers = List(
      "org.springframework.data.repository",
      "org.springframework.data.mongodb.repository",
      "org.springframework.data.jpa.repository",
      "MongoRepository",
      "CrudRepository",
      "JpaRepository",
      "PagingAndSortingRepository"
    )
    val repositoryTypes =
      cpg.typeDecl
        .filter(td => td.inheritsFromTypeFullName.exists(parent => markers.exists(parent.contains)))
        .fullName
        .toSet
    cpg.call.l.filter { call =>
      val declaring = call.methodFullName.split(':').head
      val owner     = declaring.substring(0, math.max(declaring.lastIndexOf('.'), 0))
      repositoryTypes.contains(owner)
    }.map(_.id).toSet
  }

  private def withFixtureCpg[A](fixture: String)(body: Cpg => A): A = {
    val config = Config()
      .withDelombokMode("types-only")
      .withInputPath(Paths.get("fixtures").resolve(fixture).toAbsolutePath.toString)
      .withOutputPath(Files.createTempFile("wadi-e7", ".cpg").toString)
      .withIgnoredFilesRegex(WadiPipeline.ExcludeRegex)
    Using.resource(new JavaSrc2Cpg().createCpg(config).get) { cpg =>
      X2Cpg.applyDefaultOverlays(cpg)
      body(cpg)
    }
  }

  /** Tags with both rules in one graph: (pre-2.10 ids, shipped-pass ids). */
  private def bothRules(cpg: Cpg): (Set[Long], Set[Long]) = {
    val before = preTransitiveDbCallIds(cpg)
    new SpringDataSinkPass(cpg).createAndApply()
    (before, cpg.call.where(_.tag.nameExact("sink").valueExact("db")).id.toSet)
  }

  /** The nine fixtures that predate Phase 2.10, with the size of each one's
    * pre-transitive `sink=db` set. petstore-system is tagged as one tree,
    * which is a superset of what any single module sees.
    */
  private val existingFixtures: List[(String, Int)] = List(
    "control-flow-matrix"    -> 0,
    "lombok-mini"            -> 0,
    "petstore-system"        -> 0, // StockRepository is a plain @Component
    "response-shape-mini"    -> 0,
    "restclient-yas-mini"    -> 0,
    "spring-auth-matrix"     -> 0,
    "spring-petstore-mini"   -> 2,
    "token-propagation-mini" -> 0,
    "unbound-reasons-mini"   -> 1
  )

  existingFixtures.foreach { case (fixture, recordedSize) =>
    test(s"E7 $fixture: the db-tagged call ids are unchanged by transitive detection") {
      val (before, after) = withFixtureCpg(fixture)(bothRules)
      info(s"$fixture: before ${before.size}, after ${after.size}")
      after shouldBe before
      before.size shouldBe recordedSize
    }
  }

  test("E7 spring-data-crud-matrix: transitive detection adds exactly the base-interface repositories' calls") {
    // The nine fixtures above hold three db calls between them, so they show
    // the rule did not MOVE; this shows what it ADDS. IssueRepository and
    // TicketRepository are the types here that reach their marker only
    // through a project interface.
    withFixtureCpg("spring-data-crud-matrix") { cpg =>
      val (before, after) = bothRules(cpg)
      val added           = cpg.call.id(after.diff(before).toSeq*).l
      info(s"spring-data-crud-matrix: before ${before.size}, after ${after.size}")
      before.subsetOf(after) shouldBe true
      added.map(_.methodFullName.split(':').head).sorted shouldBe List(
        "com.acme.crud.repo.IssueRepository.findAllByIdIn",
        "com.acme.crud.repo.IssueRepository.findById",
        "com.acme.crud.repo.IssueRepository.findOpen",
        "com.acme.crud.repo.TicketRepository.findById"
      )
    }
  }

  test("M0 probe: the extends clause is held by TYPE_DECL.genericSignature, not by code or inheritance") {
    // §5.2.17 "The probe (M0)". Pinned so a Joern bump that moves the text
    // fails here, beside the evidence, rather than as unbound entities.
    withFixtureCpg("spring-data-crud-matrix") { cpg =>
      val issue = cpg.typeDecl.fullNameExact("com.acme.crud.repo.IssueRepository").head
      val base  = cpg.typeDecl.fullNameExact("com.acme.crud.repo.BaseRepository").head
      val crm   = cpg.typeDecl.fullNameExact("com.acme.crud.repo.CrmAccountRepository").head
      issue.code shouldBe "public interface IssueRepository"
      issue.inheritsFromTypeFullName.l shouldBe List("com.acme.crud.repo.BaseRepository")
      issue.genericSignature shouldBe "LObject;LBaseRepository<LIssue;>;"
      // The declaring side keeps its parameter list, which binding needs.
      base.code shouldBe "public interface BaseRepository<E>"
      base.genericSignature shouldBe "<E:LObject;>LObject;LJpaRepository<LE;LLong;>;"
      // Names are as WRITTEN: `Account` here means com.acme.crud.crm.Account
      // only through this file's import.
      crm.genericSignature shouldBe "LObject;LJpaRepository<LAccount;LLong;>;"
    }
  }
}
