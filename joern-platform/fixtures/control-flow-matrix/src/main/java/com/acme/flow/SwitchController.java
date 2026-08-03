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
}
