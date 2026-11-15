package com.acme.saves.service;

import com.acme.saves.domain.Widget;
import com.acme.saves.repo.WidgetRepository;
import org.springframework.stereotype.Service;

@Service
public class WidgetWriter {

    private final WidgetRepository widgetRepository;

    public WidgetWriter(WidgetRepository widgetRepository) {
        this.widgetRepository = widgetRepository;
    }

    /** One caller in an endpoint flow, one in a class nothing reaches. */
    public Widget storeFromTwoPlaces(Widget widget) {
        return widgetRepository.save(widget);
    }
}
