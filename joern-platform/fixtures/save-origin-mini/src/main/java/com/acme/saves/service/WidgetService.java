package com.acme.saves.service;

import com.acme.saves.domain.Widget;

/** Called through the interface; the DI pass links the call to the impl. */
public interface WidgetService {

    Widget store(Widget widget);
}
