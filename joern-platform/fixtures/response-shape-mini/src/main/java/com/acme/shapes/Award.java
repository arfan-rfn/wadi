package com.acme.shapes;

import java.util.List;

/** Part of the §5.2.15 entity graph — see {@link Contest}. */
public class Award {

    private String id;
    private String name;
    private List<Contest> contests;
    private Contest primaryContest;
    private List<Team> teams;
    private Team primaryTeam;
    private List<Person> persons;
    private Person primaryPerson;
    private List<Site> sites;
    private Site primarySite;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public List<Contest> getContests() {
        return contests;
    }

    public Contest getPrimaryContest() {
        return primaryContest;
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
}
