package com.acme.saves.web;

import com.acme.saves.domain.SpecialWidget;
import com.acme.saves.domain.Widget;
import com.acme.saves.repo.WidgetRepository;
import com.acme.saves.service.WidgetService;
import com.acme.saves.service.WidgetWriter;
import java.util.ArrayList;
import java.util.List;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Argument-origin shapes (Q22) and the caller hop (R1-27). */
@RestController
@RequestMapping("/save/origin")
public class OriginShapesController {

    private final WidgetRepository widgetRepository;
    private final WidgetWriter widgetWriter;
    private final WidgetService widgetService;
    private final Widget template = new Widget("template");

    public OriginShapesController(
            WidgetRepository widgetRepository, WidgetWriter widgetWriter, WidgetService widgetService) {
        this.widgetRepository = widgetRepository;
        this.widgetWriter = widgetWriter;
        this.widgetService = widgetService;
    }

    /** The classic upsert: read, or a new one. */
    @PostMapping("/orelse-constructed")
    public Widget orElseConstructed(@RequestParam String id) {
        Widget widget = widgetRepository.findById(id).orElse(new Widget(id));
        return widgetRepository.save(widget);
    }

    /** `orElse(null)`: a null is no alternative entity. */
    @PostMapping("/orelse-null")
    public Widget orElseNull(@RequestParam String id) {
        Widget widget = widgetRepository.findById(id).orElse(null);
        return widgetRepository.save(widget);
    }

    /** A builder seeded from the read widget: not a construction. */
    @PostMapping("/to-builder")
    public Widget toBuilder(@RequestParam String id, @RequestParam String name) {
        Widget widget = widgetRepository.findById(id).orElseThrow();
        return widgetRepository.save(widget.toBuilder().name(name).build());
    }

    /** A definition after the save does not reach it. */
    @PostMapping("/reassigned-after-save")
    public Widget reassignedAfterSave(@RequestParam String id) {
        Widget widget = widgetRepository.findById(id).orElseThrow();
        Widget saved = widgetRepository.save(widget);
        widget = new Widget(id + "-next");
        return saved;
    }

    /** The parameter is overwritten by a read before the save. */
    @PostMapping("/parameter-reassigned")
    public Widget parameterReassigned(@RequestBody Widget body) {
        body = widgetRepository.findById(body.getId()).orElseThrow();
        return widgetRepository.save(body);
    }

    @PostMapping("/ternary")
    public Widget ternary(@RequestParam String id, @RequestParam boolean fresh) {
        return widgetRepository.save(fresh ? new Widget(id) : widgetRepository.findById(id).orElseThrow());
    }

    @PostMapping("/field")
    public Widget field() {
        return widgetRepository.save(template);
    }

    @PostMapping("/cast")
    public Widget cast(@RequestBody Object body) {
        return widgetRepository.save((Widget) body);
    }

    /** A new list is not a new entity. */
    @PostMapping("/list-alloc-save-all")
    public void listAllocSaveAll(@RequestParam String id) {
        List<Widget> batch = new ArrayList<>();
        batch.add(new Widget(id));
        widgetRepository.saveAll(batch);
    }

    @PostMapping("/subtype-constructed")
    public Widget subtypeConstructed(@RequestParam String id) {
        return widgetRepository.save(new SpecialWidget(id));
    }

    /** The save's argument is the lambda's own parameter, and a lambda has
     *  no call site to hop to. */
    @PostMapping("/lambda-parameter-no-caller")
    public void lambdaParameterNoCaller(@RequestBody List<Widget> widgets) {
        widgets.forEach(widget -> widgetRepository.save(widget));
    }

    @PostMapping("/caller-outside-export")
    public Widget callerOutsideExport(@RequestParam String id) {
        Widget widget = widgetRepository.findById(id).orElseThrow();
        return widgetWriter.storeFromTwoPlaces(widget);
    }

    @PostMapping("/di-interface-caller")
    public Widget diInterfaceCaller(@RequestParam String id) {
        Widget widget = widgetRepository.findById(id).orElseThrow();
        return widgetService.store(widget);
    }
}
