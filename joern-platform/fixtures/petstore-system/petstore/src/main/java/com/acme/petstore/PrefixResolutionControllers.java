package com.acme.petstore;

import static com.acme.petstore.PrefixConstants.AMBIGUOUS;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The three ways a class-prefix expression can fail to resolve, and what each
 * must produce (§5.4.2, recorded 2026-08-05).
 *
 * <p>A concatenated prefix used to fall back to its first quoted string. That
 * is not a smaller answer, it is a DIFFERENT route: two controllers whose
 * prefixes both truncated to the same tail produced identical URIs, and since
 * endpoint ids are content-derived from the URI, one silently replaced the
 * other. Three endpoints of a real controller disappeared with every honesty
 * surface reading clean.
 *
 * <p>So an operand that cannot be resolved becomes a HOLE, never nothing. A
 * holed path is imprecise but unique, which costs precision and never a row.
 */
final class PrefixConstants {

    /** Plain literal — the resolvable baseline. */
    static final String BASE = "/base";

    /** A constant whose initializer is itself a constant EXPRESSION. Java keeps
     * every link compile-time constant, so this is fully determined and must
     * resolve rather than hole. */
    static final String CHAINED = BASE + "/chained";

    /** Half of an ambiguous pair — see {@link PrefixConstantsRival}. */
    static final String AMBIGUOUS = "/left";

    private PrefixConstants() {}
}

final class PrefixConstantsRival {

    /** Same simple name, DIFFERENT value. A bare reference cannot be told
     * apart by name alone, so resolution must decline rather than pick. */
    static final String AMBIGUOUS = "/right";

    private PrefixConstantsRival() {}
}

/** Chained constant: fully determined, so the URI must be complete. */
@RestController
@RequestMapping(PrefixConstants.CHAINED + "/pets")
class ChainedPrefixController {

    @GetMapping("/list")
    public String list() {
        return "chained";
    }
}

/** Ambiguous constant reached by STATIC IMPORT: a bare name that two classes
 * declare with different values. A qualifier would disambiguate it — that is
 * why the reference here is bare. Nothing in the graph says which one Java
 * picked, so resolution must decline and hole rather than choose, and
 * critically must not fall back to the bare tail, which would collide with any
 * other controller mapping the same suffix. */
@RestController
@RequestMapping(AMBIGUOUS + "/pets")
class AmbiguousPrefixController {

    @GetMapping("/list")
    public String list() {
        return "ambiguous";
    }
}

/** Constant declared outside the analyzed source (a jar, another repo) — the
 * case the operator is most likely to hit. Same rule: hole, not truncate. */
@RestController
@RequestMapping(ExternalRoutes.OFFSITE + "/pets")
class ExternalPrefixController {

    @GetMapping("/list")
    public String list() {
        return "external";
    }
}
