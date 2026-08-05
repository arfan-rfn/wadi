package com.acme.flow;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** One handler per switch flavour, including the shapes javac desugars
 * (switch-on-string) and the fallthrough case the graph must not flatten. */
@RestController
public class SwitchController {

    enum Size { SMALL, MEDIUM, LARGE }

    @GetMapping("/switch/classic/{n}")
    public String classic(@PathVariable int n) {
        String label;
        switch (n) {
            case 0:
                label = "zero";
                break;
            case 1:
                label = "one";
                break;
            default:
                label = "many";
                break;
        }
        return label;
    }

    @GetMapping("/switch/fallthrough/{n}")
    public String fallthrough(@PathVariable int n) {
        int score = 0;
        switch (n) {
            case 2:
                score += 10;
                // deliberate fallthrough
            case 1:
                score += 10;
                break;
            default:
                score = -1;
        }
        return String.valueOf(score);
    }

    @GetMapping("/switch/string/{word}")
    public String onString(@PathVariable String word) {
        switch (word) {
            case "start":
                return "starting";
            case "stop":
                return "stopping";
            default:
                return "unknown";
        }
    }

    @GetMapping("/switch/enum/{size}")
    public String onEnum(@PathVariable Size size) {
        switch (size) {
            case SMALL:
                return "s";
            case MEDIUM:
                return "m";
            default:
                return "l";
        }
    }

    @GetMapping("/switch/arrow/{n}")
    public String arrow(@PathVariable int n) {
        return switch (n) {
            case 0 -> "zero";
            case 1, 2 -> "few";
            default -> "many";
        };
    }

    @GetMapping("/switch/yield/{n}")
    public String yieldForm(@PathVariable int n) {
        int bucket = switch (n) {
            case 0 -> 0;
            default -> {
                int magnitude = Math.abs(n);
                yield magnitude > 10 ? 2 : 1;
            }
        };
        return String.valueOf(bucket);
    }

    /** A switch INSIDE a loop, every arm breaking (§5.2.8, 2026-08-05).
     *
     * `break` binds to the nearest enclosing breakable construct, and a switch
     * is one (JLS §14.15). The jump resolver collected only enclosing LOOPS,
     * so this break matched the loop — its raw target, the statement after the
     * switch, lies inside the loop's interior — and was redirected to the
     * loop's EXIT. The map then claimed these arms leave the loop after one
     * iteration, and the statement after the switch had no incoming edge.
     *
     * The `continue` is here on purpose: it must still bind to the loop, since
     * a switch does not capture it. */
    @GetMapping("/switch/in-loop/{n}")
    public String switchInsideLoop(@PathVariable int n) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < n; i++) {
            if (i == 3) {
                continue;
            }
            String tag = "";
            switch (i % 3) {
                case 0:
                    tag = "zero";
                    break;
                case 1:
                    tag = "one";
                    break;
                default:
                    break;
            }
            out.append(tag);
        }
        return out.toString();
    }
}
