package com.acme.saves.web;

import com.acme.saves.domain.Widget;
import com.acme.saves.repo.GadgetRepository;
import com.acme.saves.repo.WidgetRepository;
import java.util.Optional;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Existence-check shapes for `guard_arm` (Q23): each saves a new widget,
 *  so only the arm differs. */
@RestController
@RequestMapping("/save/guard")
public class GuardShapesController {

    private final WidgetRepository widgetRepository;
    private final GadgetRepository gadgetRepository;

    public GuardShapesController(WidgetRepository widgetRepository, GadgetRepository gadgetRepository) {
        this.widgetRepository = widgetRepository;
        this.gadgetRepository = gadgetRepository;
    }

    /** `== null` on a local holding the lookup: true means not found. */
    @PostMapping("/null-check-not-found")
    public Widget nullCheckNotFound(@RequestParam String code) {
        Widget existing = widgetRepository.findByCode(code);
        if (existing == null) {
            return widgetRepository.save(new Widget(code));
        }
        return existing;
    }

    @PostMapping("/not-null-found")
    public Widget notNullFound(@RequestParam String code) {
        Widget existing = widgetRepository.findByCode(code);
        if (existing != null) {
            Widget replacement = new Widget(existing.getId());
            return widgetRepository.save(replacement);
        }
        return null;
    }

    /** The else arm of a not-found test is the found arm. */
    @PostMapping("/null-check-else-arm")
    public Widget nullCheckElseArm(@RequestParam String code) {
        if (widgetRepository.findByCode(code) == null) {
            return null;
        } else {
            return widgetRepository.save(new Widget(code));
        }
    }

    @PostMapping("/is-present-local")
    public Widget isPresentLocal(@RequestParam String id) {
        Optional<Widget> existing = widgetRepository.findById(id);
        if (existing.isPresent()) {
            return widgetRepository.save(new Widget(id));
        }
        return null;
    }

    @PostMapping("/is-empty-chain")
    public Widget isEmptyChain(@RequestParam String id) {
        if (widgetRepository.findById(id).isEmpty()) {
            return widgetRepository.save(new Widget(id));
        }
        return null;
    }

    /** The exists* result through a boolean local. */
    @PostMapping("/exists-boolean-local")
    public Widget existsBooleanLocal(@RequestParam String id) {
        boolean known = widgetRepository.existsById(id);
        if (!known) {
            return widgetRepository.save(new Widget(id));
        }
        return null;
    }

    /** An arm with no braces: the save's statement is the arm itself. */
    @PostMapping("/no-braces-arm")
    public Widget noBracesArm(@RequestParam String id) {
        if (!widgetRepository.existsById(id)) return widgetRepository.save(new Widget(id));
        return null;
    }

    /** A conjunction: the then arm is not exactly the not-found arm. */
    @PostMapping("/conjunction-none")
    public Widget conjunctionNone(@RequestParam String id) {
        if (!widgetRepository.existsById(id) && id.length() > 3) {
            return widgetRepository.save(new Widget(id));
        }
        return null;
    }

    /** The save is in a loop inside the arm, not directly in it. */
    @PostMapping("/nested-loop-none")
    public void nestedLoopNone(@RequestParam String id, @RequestParam int copies) {
        if (!widgetRepository.existsById(id)) {
            for (int i = 0; i < copies; i++) {
                widgetRepository.save(new Widget(id + i));
            }
        }
    }

    /** The check is on another repository: no guard, and no lookup. */
    @PostMapping("/other-repository-none")
    public Widget otherRepositoryNone(@RequestParam String id) {
        if (!gadgetRepository.existsById(id)) {
            return widgetRepository.save(new Widget(id));
        }
        return null;
    }
}
