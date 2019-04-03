from __future__ import print_function

import sys
import timeit

from pyspark.ml import Pipeline
from pyspark.ml.classification import DecisionTreeClassifier
from pyspark.ml.feature import StringIndexer, VectorIndexer, VectorAssembler
from pyspark.ml.evaluation import MulticlassClassificationEvaluator, BinaryClassificationEvaluator
from pyspark.ml.tuning import CrossValidator, ParamGridBuilder

from pyspark.sql import SparkSession, Row
from pyspark.sql.types import StructType, StructField, StringType, IntegerType

from pyspark.ml.feature import PCA

if __name__ == "__main__":

    #Check arguments
    if len(sys.argv) < 3:
        print("Usage: train.py <csv dataset train> <which slaves and how many cores>", file=sys.stderr)
        sys.exit(-1)

    # Create spark session
    spark = SparkSession\
        .builder\
        .appName("TrainPCACrossValDecisionTreeIDS-Python")\
        .getOrCreate()

    # Define dataset schema, dataset csv generated by flowtbag https://github.com/DanielArndt/flowtbag
    schema = StructType([
        StructField("srcip", StringType(), False),              # Feature 1
        StructField("srcport", IntegerType(), False),           # Feature 2
        StructField("dstip", StringType(), False),              # Feature 3
        StructField("dstport", IntegerType(), False),           # Feature 4
        StructField("proto", IntegerType(), False),             # Feature 5
        StructField("total_fpackets", IntegerType(), False),    # Feature 6
        StructField("total_fvolume", IntegerType(), False),     # Feature 7
        StructField("total_bpackets", IntegerType(), False),    # Feature 8
        StructField("total_bvolume", IntegerType(), False),     # Feature 9
        StructField("min_fpktl", IntegerType(), False),         # Feature 10
        StructField("mean_fpktl", IntegerType(), False),        # Feature 11
        StructField("max_fpktl", IntegerType(), False),         # Feature 12
        StructField("std_fpktl", IntegerType(), False),         # Feature 13
        StructField("min_bpktl", IntegerType(), False),         # Feature 14
        StructField("mean_bpktl", IntegerType(), False),        # Feature 15
        StructField("max_bpktl", IntegerType(), False),         # Feature 16
        StructField("std_bpktl", IntegerType(), False),         # Feature 17
        StructField("min_fiat", IntegerType(), False),          # Feature 18
        StructField("mean_fiat", IntegerType(), False),         # Feature 19
        StructField("max_fiat", IntegerType(), False),          # Feature 20
        StructField("std_fiat", IntegerType(), False),          # Feature 21
        StructField("min_biat", IntegerType(), False),          # Feature 22
        StructField("mean_biat", IntegerType(), False),         # Feature 23
        StructField("max_biat", IntegerType(), False),          # Feature 24
        StructField("std_biat", IntegerType(), False),          # Feature 25
        StructField("duration", IntegerType(), False),          # Feature 26
        StructField("min_active", IntegerType(), False),        # Feature 27
        StructField("mean_active", IntegerType(), False),       # Feature 28
        StructField("max_active", IntegerType(), False),        # Feature 29
        StructField("std_active", IntegerType(), False),        # Feature 30
        StructField("min_idle", IntegerType(), False),          # Feature 31
        StructField("mean_idle", IntegerType(), False),         # Feature 32
        StructField("max_idle", IntegerType(), False),          # Feature 33
        StructField("std_idle", IntegerType(), False),          # Feature 34
        StructField("sflow_fpackets", IntegerType(), False),    # Feature 35
        StructField("sflow_fbytes", IntegerType(), False),      # Feature 36
        StructField("sflow_bpackets", IntegerType(), False),    # Feature 37
        StructField("sflow_bbytes", IntegerType(), False),      # Feature 38
        StructField("fpsh_cnt", IntegerType(), False),          # Feature 39
        StructField("bpsh_cnt", IntegerType(), False),          # Feature 40
        StructField("furg_cnt", IntegerType(), False),          # Feature 41
        StructField("burg_cnt", IntegerType(), False),          # Feature 42
        StructField("total_fhlen", IntegerType(), False),       # Feature 43
        StructField("total_bhlen", IntegerType(), False),       # Feature 44
        StructField("dscp", IntegerType(), False),              # Feature 45
        StructField("label", IntegerType(), False)              # Class Label: 0-Normal; 1-Attack
    ])

    # Load CSV data
    data = spark.read.csv(sys.argv[1], schema=schema)
    coresList = sys.argv[2:]

    # Create vector assembler to produce a feature vector for each record for use in MLlib
    # First 45 csv fields are features, the 46th field is the label. Remove IPs from features.
    assembler = VectorAssembler(inputCols=schema.names[5:-1], outputCol="baseFeatures")

    # Assemble feature vectors in new dataframe
    assembledData = assembler.transform(data)

    # Create PCA model (reduce to 6 principal componentes)
    pca = PCA(k=6, inputCol="baseFeatures", outputCol="features")

    # Reduce assembled data
    model = pca.fit(assembledData)
    reducedData = model.transform(assembledData).select("features","label")

    # Create a feature indexers to speed up categorical columns for decision tree
    featureIndexer = VectorIndexer(inputCol="features", outputCol="indexedFeatures").fit(reducedData)

    # Create a DecisionTree model trainer
    dt = DecisionTreeClassifier(labelCol="label",
				featuresCol="indexedFeatures",
				impurity='entropy',
				maxDepth=10)

    # Chain indexers and model training in a Pipeline
    pipeline = Pipeline(stages=[featureIndexer, dt])

    paramGrid = ParamGridBuilder().build()

    # Split the data into training and test sets (30% held out for testing)
    (trainingData, testData) = reducedData.randomSplit([0.7, 0.3])

    # Cross validation requires parameters on a grid.
    crossval = CrossValidator(estimator = pipeline,
                               estimatorParamMaps = paramGrid,
                               evaluator = MulticlassClassificationEvaluator(),
                               numFolds = 10)

    timerstart = timeit.default_timer()

    # Train model
    cvModel = crossval.fit(trainingData)

    timerend = timeit.default_timer()

    # Time to create model
    modelTime = timerend-timerstart

    bestModel = cvModel.bestModel

    timerstart = timeit.default_timer()

    # Make predictions
    predictions = cvModel.transform(testData)

    timerend = timeit.default_timer()

    # Time to test model
    testTime = timerend-timerstart

    # Select (prediction, true label) and compute metrics
    f1 = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction", metricName="f1").evaluate(predictions)
    precision = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction", metricName="weightedPrecision").evaluate(predictions)
    recall = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction", metricName="weightedRecall").evaluate(predictions)
    accuracy = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction", metricName="accuracy").evaluate(predictions)
    auc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC").evaluate(predictions)

    maxDepth = bestModel.stages[-1]._java_obj.parent().getMaxDepth()
    impurity = bestModel.stages[-1]._java_obj.parent().getImpurity()

    # Stop spark session
    spark.stop()

    file = open("/home/gta/catraca/results/python/csv/decisionTreePCACrossVal.csv", "a+") # Results for MATLAB
    dirname = "" # For readable results
    filename = "" # For readable results

    for i in range(len(coresList)): # [0, 1, 2, ... n]
        file.write(coresList[i]+",") # Actual # of cores for each slave is written on MATLAB results

        # If another slave is being used
        if coresList[i] != "0":
#           if i == 0:
#               dirname += "master"
#               filename += "master-"+coresList[0]+"Cores"

            # If other slaves are to be used
            if dirname != "": dirname += "+"
            if filename != "": filename += "+"

            filename += "slave0"+str(i+1)+"-"+str(coresList[i])+"Cores" # Adding slaves to filename
            dirname += "slave0"+str(i+1) # Adding slaves to dirname

    file.write(str(f1)+","+str(precision)+","+str(recall)+","+str(accuracy)+","+str(auc)+","+str(modelTime)+","+str(testTime)+"\n")
    file.close()

    file = open("/home/gta/catraca/results/python/"+ dirname +"/"+ filename +"-decisionTreePCACrossVal.txt", "a+")

    file.write("\n\n+-----------------------------------------------+\n")
    file.write("+                 Test Metrics                  +\n")
    file.write("+-----------------------------------------------+\n")
#   file.write("| Number of Cores in Master          | %s  |\n" % (coresList[0]))
    for i in range(len(coresList)):
        file.write("| Number of Cores in Slave "+str(i+1)+"         | %s  |\n" % (coresList[i]))
    file.write("| F1-Score                           | %f  |\n" % (f1))
    file.write("| Weighted Precision                 | %f  |\n" % (precision))
    file.write("| Weighted Recall                    | %f  |\n" % (recall))
    file.write("| Accuracy                           | %f  |\n" % (accuracy))
    file.write("| Area Under ROC                     | %f  |\n" % (auc))
    file.write("| Model Time (in seconds)            | %f |\n" % (modelTime))
    file.write("| Test Time (in seconds)             | %f |\n" % (testTime))
    file.write("+-----------------------------------------------+\n\n")
    file.close()
