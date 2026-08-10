package com.acme.shapes;

import java.util.List;

/**
 * The entity graph that blew the export up (§5.2.15).
 *
 * Eight types, each referencing four others, is ordinary JPA modelling and is
 * NOT a cycle along any root-to-leaf path shorter than eight — so the per-path
 * guard never fires within the depth cap and the walk fans out exponentially.
 * ICPC's real equivalent reached 3 MB and depth 25 for a single endpoint,
 * repeating `label` 520 times, and 114 MB for one service's endpoint list.
 *
 * Only a budget on OUTPUT bounds this. Depth cannot: the shape is wide, not
 * deep.
 */
public class Contest {

    private String id;
    private String name;
    private List<Team> teams;
    private Team primaryTeam;
    private List<Person> persons;
    private Person primaryPerson;
    private List<Site> sites;
    private Site primarySite;
    private List<Label> labels;
    private Label primaryLabel;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public List<Team> getTeams() {
        return teams;
    }

    public Team getPrimaryTeam() {
        return primaryTeam;
    }

    public List<Person> getPersons() {
        return persons;
    }

    public Person getPrimaryPerson() {
        return primaryPerson;
    }

    public List<Site> getSites() {
        return sites;
    }

    public Site getPrimarySite() {
        return primarySite;
    }

    public List<Label> getLabels() {
        return labels;
    }

    public Label getPrimaryLabel() {
        return primaryLabel;
    }
}
