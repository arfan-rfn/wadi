package wadi.packs

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import SpringDataRepositories.{Import, kindOf, markerOf}

/** The marker rule on its own (§5.2.17 "Hardening after the rigor review",
  * review A4). The crud-matrix fixture pins it end to end through the names
  * javasrc2cpg writes; javasrc2cpg places a wildcard-imported name itself, so
  * the bare-name path is pinned here.
  */
class SpringDataRepositoriesTest extends AnyFunSuite with Matchers {

  private val Jpa = "org.springframework.data.jpa.repository.JpaRepository"

  test("a marker is its qualified name, never a name that contains one") {
    markerOf(Jpa, Nil) shouldBe Some(Jpa)
    markerOf("com.acme.crud.repo.KeyedJpaRepository", Nil) shouldBe None
    markerOf("com.acme.crud.repo.BaseCrudRepository", Nil) shouldBe None
    markerOf("org.springframework.data.jpa.repository.JpaRepositoryHelper", Nil) shouldBe None
  }

  test("a bare simple name is a marker only when the file imports it from the marker's package") {
    val wildcard = List(Import("*", "org.springframework.data.jpa.repository", wildcard = true))
    val explicit = List(Import("JpaRepository", Jpa, wildcard = false))
    markerOf("JpaRepository", wildcard) shouldBe Some(Jpa)
    markerOf("JpaRepository", explicit) shouldBe Some(Jpa)
    markerOf("<unresolvedNamespace>.JpaRepository", wildcard) shouldBe Some(Jpa)
    // No import, or an import from somewhere else: a project type of that name.
    markerOf("JpaRepository", Nil) shouldBe None
    markerOf("JpaRepository", List(Import("*", "com.acme.repo", wildcard = true))) shouldBe None
    markerOf("JpaRepository", List(Import("*", "org.springframework.data.repository", wildcard = true))) shouldBe None
    markerOf("KeyedJpaRepository", wildcard) shouldBe None
  }

  test("the kind is the marker's store") {
    kindOf(Jpa) shouldBe "jpa"
    kindOf("org.springframework.data.jpa.repository.support.SimpleJpaRepository") shouldBe "jpa"
    kindOf("org.springframework.data.mongodb.repository.MongoRepository") shouldBe "mongo"
    kindOf("org.springframework.data.repository.CrudRepository") shouldBe "other"
  }
}
