package wadi.packs

import scala.collection.mutable

/** javasrc2cpg's `genericSignature` properties, parsed (§5.2.17, the M0 probe).
  *
  * It is JVM generic-signature syntax built from the source text: names as
  * WRITTEN and dotted (`LAccount;`, `Lcom.acme.Account;`, `LOuter.Nested;`).
  * A TYPE_DECL's holds the declaration's own parameter list first
  * (`<E:LObject;>`, each with its bounds), then the superclass (`LObject;` for
  * an interface) and the interfaces with their arguments; there a type
  * variable is spelled like a class (`LE;`), so it is told apart only by the
  * enclosing declaration's parameter list. A MEMBER's or LOCAL's holds one
  * type, with a type variable as `TE;`; a METHOD's holds its own parameter
  * list, then the parameter types in parentheses (`<R:LRepo;>(TR;)J`).
  *
  * In `wadi.packs` because repository detection reads it too: a receiver
  * declared as a type variable is a repository through its bound (review A2).
  */
private[wadi] object GenericSignature {

  sealed trait Ty
  final case class ClassTy(name: String, args: List[Arg]) extends Ty
  final case class ArrayTy(element: Ty)                    extends Ty
  final case class PrimitiveTy(code: Char)                 extends Ty
  final case class VarTy(name: String)                     extends Ty

  sealed trait Arg
  case object AnyArg                                  extends Arg
  final case class WildArg(variance: Char, bound: Ty) extends Arg
  final case class ExactArg(ty: Ty)                   extends Arg

  /** A type declaration: its own parameters in order, their bounds, and the
    * types it extends. A parameter with no bound written is bounded by
    * `Object` (`<E:LObject;>`).
    */
  final case class Decl(params: List[String], supers: List[ClassTy], bounds: Map[String, List[Ty]] = Map.empty)

  /** A method: its own type parameters' bounds and its parameter types, in
    * order, the receiver excluded.
    */
  final case class MethodSig(bounds: Map[String, List[Ty]], params: List[Ty])

  /** None on anything unexpected: an unreadable chain is an unbound entity,
    * never a guess.
    */
  def parseDecl(signature: String): Option[Decl] =
    if (signature == null || signature.isEmpty || signature == "<empty>") None
    else {
      val reader = new Reader(signature)
      try {
        val params = if (reader.peek == '<') reader.typeParams() else Nil
        val supers = mutable.ListBuffer.empty[ClassTy]
        while (!reader.atEnd) supers += reader.classTy()
        Some(Decl(params.map(_._1), supers.toList, params.toMap))
      } catch { case _: Reader.Malformed => None }
    }

  /** One type: a MEMBER's or LOCAL's signature (`LCrudRepository<LOrder;LLong;>;`,
    * `TR;`). None on anything unexpected, trailing text included.
    */
  def parseType(signature: String): Option[Ty] =
    if (signature == null || signature.isEmpty || signature == "<empty>") None
    else {
      val reader = new Reader(signature)
      try {
        val ty = reader.ty()
        Option.when(reader.atEnd)(ty)
      } catch { case _: Reader.Malformed => None }
    }

  /** A METHOD's signature, up to its parameter list; the return type and any
    * `throws` are not read.
    */
  def parseMethod(signature: String): Option[MethodSig] =
    if (signature == null || signature.isEmpty || signature == "<empty>") None
    else {
      val reader = new Reader(signature)
      try {
        val bounds = if (reader.peek == '<') reader.typeParams() else Nil
        Some(MethodSig(bounds.toMap, reader.parameterTypes()))
      } catch { case _: Reader.Malformed => None }
    }

  /** Java source text for a type: `Map<String, List<Integer>>`, `byte[]`. */
  def render(ty: Ty): String = ty match {
    case ClassTy(name, Nil)  => name
    case ClassTy(name, args) => s"$name<${args.map(renderArg).mkString(", ")}>"
    case ArrayTy(element)    => s"${render(element)}[]"
    case PrimitiveTy(code)   => Primitives.getOrElse(code, code.toString)
    case VarTy(name)         => name
  }

  private def renderArg(arg: Arg): String = arg match {
    case AnyArg                => "?"
    case WildArg('+', bound)   => s"? extends ${render(bound)}"
    case WildArg(_, bound)     => s"? super ${render(bound)}"
    case ExactArg(ty)          => render(ty)
  }

  private val Primitives: Map[Char, String] = Map(
    'B' -> "byte", 'C' -> "char", 'D' -> "double", 'F' -> "float", 'I' -> "int",
    'J' -> "long", 'S' -> "short", 'Z' -> "boolean", 'V' -> "void"
  )

  private object Reader {
    final class Malformed extends RuntimeException(null, null, false, false)
  }

  private final class Reader(text: String) {
    private var at = 0

    def atEnd: Boolean = at >= text.length
    def peek: Char     = if (atEnd) throw new Reader.Malformed else text.charAt(at)
    private def next(): Char = { val c = peek; at += 1; c }
    private def expect(c: Char): Unit = if (next() != c) throw new Reader.Malformed

    /** `<K:LObject;E:LComparable<LE;>;>`: each name, in order, with its bounds. */
    def typeParams(): List[(String, List[Ty])] = {
      expect('<')
      val params = mutable.ListBuffer.empty[(String, List[Ty])]
      while (peek != '>') {
        val start = at
        while (peek != ':') at += 1
        val name   = text.substring(start, at)
        val bounds = mutable.ListBuffer.empty[Ty]
        // One class bound and any interface bounds, each after a ':'; the
        // class bound may be empty (`T::LIface;`).
        while (!atEnd && peek == ':') {
          at += 1
          if (peek != ':' && peek != '>' && !isParamStart) bounds += ty()
        }
        params += name -> bounds.toList
      }
      expect('>')
      params.toList
    }

    /** `(TR;LString;)`: the types between the parentheses. */
    def parameterTypes(): List[Ty] = {
      expect('(')
      val params = mutable.ListBuffer.empty[Ty]
      while (peek != ')') params += ty()
      expect(')')
      params.toList
    }

    /** After a bound, a new parameter starts with an identifier and a ':'. */
    private def isParamStart: Boolean = {
      var i = at
      while (i < text.length && Character.isJavaIdentifierPart(text.charAt(i))) i += 1
      i > at && i < text.length && text.charAt(i) == ':'
    }

    def ty(): Ty = peek match {
      case 'L' => classTy()
      case '[' => at += 1; ArrayTy(ty())
      case 'T' =>
        at += 1
        val start = at
        while (peek != ';') at += 1
        val name = text.substring(start, at)
        at += 1
        VarTy(name)
      case c if Primitives.contains(c) => at += 1; PrimitiveTy(c)
      case _                           => throw new Reader.Malformed
    }

    def classTy(): ClassTy = {
      expect('L')
      val start = at
      while (peek != '<' && peek != ';') at += 1
      val name = text.substring(start, at)
      val args =
        if (peek == '<') {
          at += 1
          val buffer = mutable.ListBuffer.empty[Arg]
          while (peek != '>') buffer += arg()
          at += 1
          buffer.toList
        } else Nil
      // A suffix after the arguments (`LOuter<LA;>.Inner;`) is not a shape
      // the frontend was seen to write; refuse it rather than misread it.
      expect(';')
      if (name.isEmpty) throw new Reader.Malformed
      ClassTy(name, args)
    }

    private def arg(): Arg = peek match {
      case '*'       => at += 1; AnyArg
      case '+' | '-' => val v = next(); WildArg(v, ty())
      case _         => ExactArg(ty())
    }
  }
}
