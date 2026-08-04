// Wadi joern-platform (architecture.md §5.1): everything that must see inside
// a single service's code graph. Depends on stock, pinned Joern (P5) — never a fork.

name := "wadi-joern-platform"
organization := "com.trywadi"
version := "0.5.2"

// Must track the Scala minor Joern publishes with (Scala 3 artifacts).
scalaVersion := "3.8.3"

// One pin, everywhere: this version must equal the Joern release baked into
// the wadi-joern image (Dockerfile) — rolling releases change internals freely.
val joernVersion = "4.0.593"

resolvers ++= Seq(
  Resolver.mavenLocal,
  "Sonatype OSS" at "https://oss.sonatype.org/content/repositories/public",
  // gradle-tooling-api (transitive via javasrc2cpg) lives in Gradle's own repo.
  "Gradle Releases" at "https://repo.gradle.org/gradle/libs-releases"
)

// Joern artifacts are Provided: at runtime our jar sits on Joern's own
// classpath inside the wadi-joern image, so the assembly must contain only
// wadi code + upickle (assembly excludes Provided; tests still see them).
libraryDependencies ++= Seq(
  "io.joern" %% "x2cpg"             % joernVersion % Provided,
  "io.joern" %% "javasrc2cpg"       % joernVersion % Provided,
  "io.joern" %% "semanticcpg"       % joernVersion % Provided,
  "io.joern" %% "dataflowengineoss" % joernVersion % Provided,
  "com.lihaoyi" %% "upickle"        % "4.0.2",
  "org.scalatest" %% "scalatest"    % "3.2.19" % Test,
  // §5.2.8 M3 bytecode oracle: pinned to javasrc2cpg's transitive ASM so the
  // test classpath never carries two ASM versions. Test-only — the shipped
  // assembly is unchanged.
  "org.ow2.asm" % "asm-tree" % "9.9.1" % Test
)

assembly / assemblyMergeStrategy := {
  case PathList("META-INF", _*) => MergeStrategy.discard
  case _                        => MergeStrategy.first
}
assembly / assemblyJarName := "wadi-joern-platform.jar"

scalacOptions ++= Seq(
  "-deprecation",
  "-feature",
  "-Werror"
)

Test / fork := true
// Joern frontends want real heap during fixture CPG construction.
Test / javaOptions ++= Seq("-Xmx4G")
