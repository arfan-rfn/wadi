package com.acme.saves.service;

import com.acme.saves.domain.Widget;
import com.acme.saves.repo.WidgetRepository;
import org.springframework.stereotype.Service;

@Service
public class WidgetServiceImpl implements WidgetService {

    private final WidgetRepository widgetRepository;

    public WidgetServiceImpl(WidgetRepository widgetRepository) {
        this.widgetRepository = widgetRepository;
    }

    @Override
    public Widget store(Widget widget) {
        return widgetRepository.save(widget);
    }
}
