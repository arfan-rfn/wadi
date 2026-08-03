package com.acme.petstore;

import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.acme.common.StockQuery;
import com.external.vendor.VendorInfo;

/** M5 probes (§5.2.7): provider-side wire shapes — nested DTOs + Jackson,
 * generic unwrapping, request bodies, cycles, staged-library DTOs, and the
 * honest unresolved terminal for off-CPG types. */
@RestController
@RequestMapping("/catalog")
public class CatalogController {

    @GetMapping("/pets/{id}")
    public PetDetails details(@PathVariable String id) {
        return new PetDetails();
    }

    @GetMapping("/pets")
    public ResponseEntity<List<PetDetails>> list() {
        return ResponseEntity.ok(List.of());
    }

    @PostMapping("/pets")
    public PetDetails create(@RequestBody NewPetRequest payload) {
        return new PetDetails();
    }

    @GetMapping("/tree")
    public Category tree() {
        return new Category();
    }

    /** The staged-library DTO (§5.2.6 union): shape walks wadi-libs source. */
    @GetMapping("/query-shape")
    public StockQuery queryShape() {
        return new StockQuery();
    }

    /** Off-CPG type: the shape is an honest `unresolved` name, never fields. */
    @GetMapping("/vendor")
    public VendorInfo vendor() {
        return new VendorInfo();
    }
}
