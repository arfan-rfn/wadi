package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers
import wadi.packs.AsyncRootKind

import java.nio.file.{Files, Paths}

/** §7 (recorded 2026-08-05) — the cross-language vocabulary gate.
  *
  * `async-root` tag values are emitted by a Scala pack and validated by a
  * Python contract (`ASYNC_ROOT_KINDS`). No type system spans that boundary,
  * so the two lists were hand-maintained in different languages with nothing
  * connecting them — the same shape of drift that took a snapshot down on
  * 2026-08-05, when `unlabeled-arm` shipped in the producer and never reached
  * its registry. That one only surfaced on a user's repository, which is
  * exactly where a check must never first fire.
  *
  * The contract owns the vocabulary and publishes it as data (`make schema` →
  * `schemas/vocabulary/async_root_kinds.json`); this test diffs the pack's
  * enumeration against it **in both directions**, so a kind added on either
  * side without the other fails the build. A registered value nothing emits is
  * as much a defect as an emitted value nothing registers (§7): for a P10 gap
  * registry, a consumer filtering for a never-emitted code cannot distinguish
  * "no such gaps" from "never implemented".
  */
class AsyncRootVocabularyTest extends AnyFunSuite with Matchers {

  private val publishedPath =
    Paths.get("..", "schemas", "vocabulary", "async_root_kinds.json").toAbsolutePath.normalize

  test("the pack's async-root vocabulary matches the published contract registry") {
    withClue(
      s"missing $publishedPath — run `make schema` at the repo root to publish the registry: "
    ) {
      Files.exists(publishedPath) shouldBe true
    }

    val published = ujson.read(Files.readString(publishedPath))
    val registry  = published("values").arr.map(_.str).toSet
    val emitted   = AsyncRootKind.All

    withClue(
      "kinds this pack emits that the contract does not register — add them to " +
        "ASYNC_ROOT_KINDS in wadi_contracts.tags and re-run `make schema`: "
    ) {
      (emitted diff registry) shouldBe empty
    }

    withClue(
      "kinds the contract registers that this pack never emits — either emit " +
        "them or record the removal (the host-unresolvable precedent, §5.4.2): "
    ) {
      (registry diff emitted) shouldBe empty
    }
  }

  test("every emitted kind is reachable from a tagging site in SpringAsyncRootPass") {
    // Guards the other half of liveness: `All` is hand-written, so a constant
    // could be listed there and never used at a `newTagNodePair` site. The
    // pass source is the evidence — a kind must appear in it to count as
    // emitted, which is what makes the diff above meaningful.
    val passSource = Files.readString(
      Paths.get("src", "main", "scala", "wadi", "packs", "SpringPacks.scala").toAbsolutePath
    )
    val body = passSource
      .split("class SpringAsyncRootPass")
      .lift(1)
      .getOrElse(fail("SpringAsyncRootPass not found in SpringPacks.scala"))

    val constantNames = Map(
      AsyncRootKind.Scheduled         -> "AsyncRootKind.Scheduled",
      AsyncRootKind.EventListener     -> "AsyncRootKind.EventListener",
      AsyncRootKind.KafkaListener     -> "AsyncRootKind.KafkaListener",
      AsyncRootKind.RabbitListener    -> "AsyncRootKind.RabbitListener",
      AsyncRootKind.JmsListener       -> "AsyncRootKind.JmsListener",
      AsyncRootKind.ApplicationRunner -> "AsyncRootKind.ApplicationRunner",
      AsyncRootKind.Bean              -> "AsyncRootKind.Bean",
      AsyncRootKind.FrameworkCallback -> "AsyncRootKind.FrameworkCallback"
    )

    constantNames.keySet shouldBe AsyncRootKind.All

    val unused = constantNames.collect {
      case (kind, reference) if !body.contains(reference) => kind
    }
    withClue("declared in AsyncRootKind.All but never referenced by the pass: ") {
      unused shouldBe empty
    }
  }
}
