package online

import org.apache.spark.ml.classification.RandomForestClassifier
import org.apache.spark.ml.feature.{PCA, VectorIndexer}
import org.apache.spark.ml.Pipeline
import org.apache.spark.sql.functions._
import org.apache.spark.sql.SparkSession
import org.apache.spark.sql.types._

import br.ufrj.gta.stream.schema.GTA
import br.ufrj.gta.stream.util.{File, Metrics}

object RandomForest {
    def main(args: Array[String]) {
        val sep = ","
        val labelCol = "label"

        val pcaFeaturesCol = "pcaFeatures"
        //val indexedFeaturesCol = "indexedFeatures"
        var featuresCol = "features"

        val schema = GTA.getSchema

        val spark = SparkSession.builder.appName("Stream").getOrCreate()

        if (args.length < 8) {
            println("Missing parameters")
            sys.exit(1)
        }

        val inputTrainingFile = args(0)
        val inputTestPath = args(1)
        val outputPath = File.appendSlash(args(2))
        val outputMetricsPath = File.appendSlash(args(3))
        val timeoutStream = args(4).toLong
        val numTrees = args(5).toInt
        val impurity = args(6)
        val maxDepth = args(7).toInt
        //val maxCategories = args(8).toInt
        val pcaK: Option[Int] = try {
            Some(args(8).toInt)
        } catch {
            case e: Exception => None
        }

        val inputTrainingData = spark.read
            .option("sep", sep)
            .option("header", false)
            .schema(schema)
            .csv(inputTrainingFile)

        val inputTestDataStream = spark.readStream
            .option("sep", sep)
            .option("header", false)
            .schema(schema)
            .csv(inputTestPath)

        val featurizedTrainingData = GTA.featurize(inputTrainingData, featuresCol)
        val featurizedTestData = GTA.featurize(inputTestDataStream, featuresCol)

        val (trainingData, testData, metricsFilename) = pcaK match {
            case Some(pcaK) => {
                val pca = new PCA()
                    .setInputCol(featuresCol)
                    .setOutputCol(pcaFeaturesCol)
                    .setK(pcaK)
                    .fit(featurizedTrainingData)

                featuresCol = pcaFeaturesCol

                (pca.transform(featurizedTrainingData), pca.transform(featurizedTestData), "online_random_forest_pca.csv")
            }
            case None => (featurizedTrainingData, featurizedTestData, "online_random_forest.csv")
        }

        val classifier = new RandomForestClassifier()
            .setFeaturesCol(featuresCol)
            .setLabelCol(labelCol)
            .setNumTrees(numTrees)
            .setImpurity(impurity)
            .setMaxDepth(maxDepth)

        // TODO: add a vector indexer to this pipeline
        val pipeline = new Pipeline()
            .setStages(Array(classifier))

        val model = pipeline.fit(trainingData)

        val prediction = model.transform(testData)

        val predictionCol = classifier.getPredictionCol

        val outputDataStream = prediction.select(prediction(labelCol), prediction(predictionCol)).writeStream
            .outputMode("append")
            .option("checkpointLocation", outputPath + "checkpoints/")
            .format("csv")
            .option("path", outputPath)
            .start()

        outputDataStream.awaitTermination(timeoutStream)

        var metrics = Metrics.empty(Metrics.DefaultMetrics: _*)

        val inputResultData = spark.read
            .option("sep", sep)
            .option("header", false)
            .schema(new StructType().add(labelCol, "integer").add(predictionCol, "double"))
            .csv(outputPath + "*.csv")

        metrics = metrics.add(Metrics.getPrediction(inputResultData, labelCol, predictionCol))

        metrics.export(outputMetricsPath + metricsFilename, Metrics.FormatCsv)

        spark.stop()
    }
}
