package wadi.`export`

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import wadi.packs.GenericSignature
import GenericSignature.*

/** The TYPE_DECL.genericSignature reader (§5.2.17, the M0 probe).
  *
  * Every input is a string javasrc2cpg 4.0.593 wrote for a real declaration
  * during the probe; the declaration is in each test's name. The crud-matrix
  * fixture exercises the common shapes end to end; these are the ones it does
  * not hold, read directly so a frontend change shows up as a parse change.
  */
class GenericSignatureTest extends AnyFunSuite with Matchers {

  private def firstArgOf(signature: String, superName: String): Option[Arg] =
    parseDecl(signature).flatMap(_.supers.find(_.name == superName)).flatMap(_.args.headOption)

  test("interface TwoParam<K, E extends Comparable<E>> extends CrudRepository<E, K>") {
    val decl = parseDecl("<K:LObject;E:LComparable<LE;>;>LObject;LCrudRepository<LE;LK;>;").get
    // Names only, in declaration order: that order is what binding uses.
    decl.params shouldBe List("K", "E")
    decl.supers.map(_.name) shouldBe List("Object", "CrudRepository")
    decl.supers(1).args shouldBe List(ExactArg(ClassTy("E", Nil)), ExactArg(ClassTy("K", Nil)))
  }

  test("interface NestedRepo extends JpaRepository<Map<String, List<Integer>>, Long>") {
    firstArgOf("LObject;LJpaRepository<LMap<LString;LList<LInteger;>;>;LLong;>;", "JpaRepository")
      .collect { case ExactArg(ty) => render(ty) } shouldBe Some("Map<String, List<Integer>>")
  }

  test("interface ArrayRepo extends CrudRepository<byte[], Long>") {
    firstArgOf("LObject;LCrudRepository<[BLLong;>;", "CrudRepository")
      .collect { case ExactArg(ty) => render(ty) } shouldBe Some("byte[]")
  }

  test("interface Wild extends CrudRepository<List<? extends Number>, Long>") {
    firstArgOf("LObject;LCrudRepository<LList<+LNumber;>;LLong;>;", "CrudRepository")
      .collect { case ExactArg(ty) => render(ty) } shouldBe Some("List<? extends Number>")
  }

  test("interface QualifiedRepo extends JpaRepository<com.acme.crud.crm.Account, Long>") {
    // Qualified as written, with dots; resolution, not the parser, maps it.
    firstArgOf("LObject;LJpaRepository<Lcom.acme.crud.crm.Account;LLong;>;", "JpaRepository") shouldBe
      Some(ExactArg(ClassTy("com.acme.crud.crm.Account", Nil)))
  }

  test("interface RawRepo extends CrudRepository (raw: no argument to bind)") {
    parseDecl("LObject;LCrudRepository;").get.supers.map(s => (s.name, s.args)) shouldBe
      List(("Object", Nil), ("CrudRepository", Nil))
  }

  test("abstract class BoundedStore<R extends JpaRepository<Order, String>>: a parameter keeps its bound") {
    val decl = parseDecl("<R:LJpaRepository<LOrder;LString;>;>LObject;").get
    decl.params shouldBe List("R")
    decl.bounds("R") shouldBe List(
      ClassTy("JpaRepository", List(ExactArg(ClassTy("Order", Nil)), ExactArg(ClassTy("String", Nil))))
    )
    // No bound written is Object's.
    parseDecl("<E:LObject;>LObject;").get.bounds("E") shouldBe List(ClassTy("Object", Nil))
  }

  test("a MEMBER's or LOCAL's signature is one type; a type variable is TR;") {
    parseType("TR;") shouldBe Some(VarTy("R"))
    parseType("LJpaRepository<TE;LLong;>;") shouldBe
      Some(ClassTy("JpaRepository", List(ExactArg(VarTy("E")), ExactArg(ClassTy("Long", Nil)))))
    parseType("LCrudRepository<LOrder;LString;>;LObject;") shouldBe None
    parseType("<empty>") shouldBe None
  }

  test("<R extends CrudRepository<Thing, Long>> long viaMethodVar(R repo): bounds and parameter types") {
    val sig = parseMethod("<R:LCrudRepository<LThing;LLong;>;>(TR;)J").get
    sig.bounds("R") shouldBe List(
      ClassTy("CrudRepository", List(ExactArg(ClassTy("Thing", Nil)), ExactArg(ClassTy("Long", Nil))))
    )
    sig.params shouldBe List(VarTy("R"))
    parseMethod("(LWildRepo;LString;)Z").get.params shouldBe List(ClassTy("WildRepo", Nil), ClassTy("String", Nil))
    parseMethod("(LWildRepo;") shouldBe None
  }

  test("an unreadable signature is no declaration, never a partial one") {
    parseDecl("LObject") shouldBe None
    parseDecl("LJpaRepository<LOrder;") shouldBe None
    parseDecl("") shouldBe None
    parseDecl("<empty>") shouldBe None
  }
}
