#!/usr/bin/env bash

cd $QB_ROOT
cd ..
luigid --background

cd $SPARK_HOME
sbin/start-all.sh

cd $QB_ROOT
make clm
