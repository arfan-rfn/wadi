package com.acme.petstore;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * P8 fixture (§5.4.2 endpoint idioms): the class prefix is a static-final
 * CONSTANT (not a string literal), and the mapping declares TWO paths — one
 * endpoint per array entry. Both idioms are yas ground truth. Also the root
 * for the T2 URL-idiom and base-recovery probes.
 */
@RestController
@RequestMapping(ApiPaths.ADMIN_PETS)
public class AdminPetController {

    private final UrlIdiomsProbe urlIdiomsProbe;
    private final BaseBoundClient baseBoundClient;

    public AdminPetController(UrlIdiomsProbe urlIdiomsProbe, BaseBoundClient baseBoundClient) {
        this.urlIdiomsProbe = urlIdiomsProbe;
        this.baseBoundClient = baseBoundClient;
    }

    @GetMapping({"/summary", "/report"})
    public String overview() {
        Integer ternary = urlIdiomsProbe.viaTernary("7", false);
        Integer builder = urlIdiomsProbe.viaStringBuilder("7");
        Integer joined = urlIdiomsProbe.viaJoin("7");
        Integer formatted = urlIdiomsProbe.viaMessageFormat("7");
        Integer mapped = urlIdiomsProbe.viaConstantMap("7");
        Integer ctor = urlIdiomsProbe.viaCtorParam("7");
        Integer bound = baseBoundClient.boundStock("7");
        String mystery = baseBoundClient.unresolvableBase("7");
        Integer composeEnv = urlIdiomsProbe.viaComposeEnv("7");
        Integer profile = urlIdiomsProbe.viaProfileConfig("7");
        Integer k8s = urlIdiomsProbe.viaK8sDns("7");
        return "ok:" + ternary + builder + joined + formatted + mapped + ctor + bound + mystery
                + composeEnv + profile + k8s;
    }
}
